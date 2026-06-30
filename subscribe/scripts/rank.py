# -*- coding: utf-8 -*-

# @Author  : assistant
# @Time    : 2026-06-29
# @Desc    : 从已聚合的节点池(proxies.yaml)中筛选出两份榜单:
#            1) 干净家宽榜:仅住宅/ISP 类节点,国家分布尽量均衡,按延迟取前 N
#            2) 速度榜:全部存活节点,纯按延迟升序取前 N
#            本脚本只做"筛选加工",不负责爬取。节点来源由 process.py 预先产出。

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass

# 允许以 `python subscribe/scripts/rank.py` 方式运行时能 import 到同级模块
CURRENT = os.path.abspath(os.path.dirname(__file__))
SUBSCRIBE_DIR = os.path.dirname(CURRENT)
if SUBSCRIBE_DIR not in sys.path:
    sys.path.insert(0, SUBSCRIBE_DIR)

import location
import utils
import yaml
from logger import logger

import clash
from clash import QuotedStr, quoted_scalar

# 项目根目录
PATH = os.path.abspath(os.path.dirname(SUBSCRIBE_DIR))

# 测延迟使用的目标地址(与项目测活默认一致)
DEFAULT_TEST_URL = "https://www.google.com/generate_204"

# mihomo 外部控制器地址,用于调用 delay API 取内核实测延迟
EXTERNAL_CONTROLLER = "127.0.0.1:9090"


@dataclass
class NodeMetric:
    """单个节点的测量结果"""

    # 原始节点配置
    proxy: dict

    # 国家(中文),来自 location 检测
    country: str

    # IP 类型:isp(家宽) / business(商宽) / hosting(机房) / ""(未知)
    ip_type: str

    # 延迟(毫秒),-1 表示不可用
    delay: int


def load_proxies(filepath: str) -> list[dict]:
    """从 yaml 文件读取 proxies 列表"""
    if not filepath or not os.path.exists(filepath) or not os.path.isfile(filepath):
        logger.error(f"[Rank] proxies file not found: {filepath}")
        return []

    try:
        with open(filepath, "r", encoding="utf8") as f:
            data = yaml.load(f, Loader=yaml.SafeLoader)
    except Exception as e:
        logger.error(f"[Rank] failed to parse yaml: {filepath}, message: {str(e)}")
        return []

    if not isinstance(data, dict):
        return []

    proxies = data.get("proxies", [])
    return proxies if isinstance(proxies, list) else []


def measure_delay(proxy_name: str, test_url: str, timeout: int = 5000) -> int:
    """通过 mihomo 的 delay API 测量节点延迟,返回毫秒数,失败返回 -1

    直接复用 mihomo 内核实测的延迟(与项目 clash.check 同一接口),
    比自行计时更准确,不受重试/限速干扰。
    """
    name = utils.trim(proxy_name)
    if not name:
        return -1

    try:
        quoted_name = urllib.parse.quote(name, safe="")
        quoted_url = urllib.parse.quote(test_url, safe="")
    except Exception:
        return -1

    url = f"http://{EXTERNAL_CONTROLLER}/proxies/{quoted_name}/delay?timeout={timeout}&url={quoted_url}"

    content = utils.http_get(url=url, retry=2, interval=0.05)
    try:
        data = json.loads(content)
    except Exception:
        return -1

    delay = data.get("delay", -1)
    if not isinstance(delay, int) or delay <= 0:
        return -1

    return delay


def collect_metrics(
    proxies: list[dict],
    num_threads: int,
    test_url: str,
    delay_limit: int,
    ip_library: str,
    show_progress: bool,
) -> list[NodeMetric]:
    """启动 mihomo,对每个节点测延迟 + 查国家/IP类型,返回测量结果列表

    复用 location 模块已有的端口分配与 mihomo 启动逻辑,避免重复造轮子。
    """
    if not proxies:
        return []

    if not clash.is_mihomo():
        logger.error("[Rank] mihomo binary not found or not mihomo core, abort")
        return []

    # 节点重命名,确保名字唯一(沿用 location 的处理)
    nodes = location.rename(proxies, digits=2, shuffle=False)

    # 生成 mihomo 监听配置,每个节点分配一个本地 http 端口
    config, records = location.generate_mihomo_config(nodes)

    # 补一个 external-controller,用于调用 mihomo 的 delay API 测准确延迟
    config["external-controller"] = EXTERNAL_CONTROLLER

    workspace = os.path.join(PATH, "clash")
    config_path = os.path.join(workspace, "config.yaml")
    with open(config_path, "w", encoding="utf8") as f:
        yaml.dump(config, f, allow_unicode=True)

    mihomo_bin = os.path.join(workspace, location.which_bin()[0])
    if not os.path.exists(mihomo_bin) or not os.path.isfile(mihomo_bin):
        logger.error("[Rank] mihomo binary not found, abort")
        return []

    utils.chmod(mihomo_bin)

    # 准备 IP 信息查询所需的 mmdb 与 api key
    api_key = utils.trim(os.environ.get("IPAPI_IS_API_KEY", ""))
    mappings = {p["name"]: p for p in nodes}

    process = None
    try:
        process = subprocess.Popen(
            [mihomo_bin, "-d", workspace, "-f", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        logger.info("[Rank] waiting for mihomo to start...")
        time.sleep(8)

        # 第一步:并发测延迟(通过 mihomo delay API,内核实测,数值准确)
        names = list(records.keys())
        delay_tasks = [[name, test_url, delay_limit] for name in names]
        delay_results = utils.multi_thread_run(
            func=measure_delay,
            tasks=delay_tasks,
            num_threads=num_threads,
            show_progress=show_progress,
            description="Measuring delay",
        )

        # 节点名 -> 延迟
        port_delay = {}
        for i, name in enumerate(names):
            port_delay[name] = delay_results[i] if i < len(delay_results) else -1

        # 第二步:对延迟有效的节点查国家 + IP 类型
        alive_names = [name for name in names if 0 < port_delay.get(name, -1) <= delay_limit]
        logger.info(f"[Rank] alive nodes after delay check: {len(alive_names)} / {len(names)}")

        residential_tasks = []
        for name in alive_names:
            port = records.get(name)
            if not port:
                continue
            if api_key:
                residential_tasks.append((mappings[name], port, api_key, ip_library))
            else:
                residential_tasks.append((mappings[name], port, "", ip_library))

        residential_results = utils.multi_thread_run(
            func=location.check_residential,
            tasks=residential_tasks,
            num_threads=num_threads,
            show_progress=show_progress,
            description="Checking residential",
        )

        # name -> (country, ip_type)
        info_map = {}
        for item in residential_results:
            if item and item.success:
                info_map[item.result.name] = (item.result.country, item.result.ip_type)

        metrics = []
        for name in alive_names:
            proxy = mappings.get(name)
            if not proxy:
                continue
            country, ip_type = info_map.get(name, ("", ""))
            metrics.append(
                NodeMetric(
                    proxy=proxy,
                    country=country,
                    ip_type=ip_type,
                    delay=port_delay.get(name, -1),
                )
            )

        return metrics
    except Exception as e:
        logger.error(f"[Rank] error during measurement: {str(e)}")
        return []
    finally:
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                pass


def balanced_by_country(metrics: list[NodeMetric], limit: int) -> list[NodeMetric]:
    """国家均衡选取:按国家分桶,各桶内按延迟升序,轮转取节点直到凑满 limit

    保证各国尽量平均,同时优先取每个国家里延迟最低的。
    """
    if not metrics:
        return []

    buckets = defaultdict(list)
    for m in metrics:
        key = m.country or "未知"
        buckets[key].append(m)

    # 每个桶内按延迟升序
    for key in buckets:
        buckets[key].sort(key=lambda x: x.delay)

    # 轮转取节点
    selected, indices = [], {key: 0 for key in buckets}
    # 国家顺序按"桶内最低延迟"排序,保证整体质量倾向
    country_order = sorted(buckets.keys(), key=lambda k: buckets[k][0].delay)

    while len(selected) < limit:
        progressed = False
        for key in country_order:
            idx = indices[key]
            if idx < len(buckets[key]):
                selected.append(buckets[key][idx])
                indices[key] += 1
                progressed = True
                if len(selected) >= limit:
                    break
        if not progressed:
            # 所有桶都取空了
            break

    return selected


def save_ranklist(metrics: list[NodeMetric], filepath: str) -> None:
    """把榜单节点保存为 clash proxies yaml"""
    nodes = []
    for m in metrics:
        proxy = dict(m.proxy)
        # 清理仅用于流程的临时字段
        for k in ["sub", "chatgpt", "liveness"]:
            proxy.pop(k, None)
        nodes.append(proxy)

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w+", encoding="utf8") as f:
        yaml.add_representer(QuotedStr, quoted_scalar)
        yaml.dump({"proxies": nodes}, f, allow_unicode=True)

    logger.info(f"[Rank] saved {len(nodes)} proxies to {filepath}")


def summarize(metrics: list[NodeMetric], title: str) -> None:
    """打印榜单的国家分布概览"""
    dist = defaultdict(int)
    for m in metrics:
        dist[m.country or "未知"] += 1

    parts = ", ".join(f"{k}:{v}" for k, v in sorted(dist.items(), key=lambda x: -x[1]))
    logger.info(f"[Rank] {title} total={len(metrics)}, country distribution -> {parts}")


def main(args: argparse.Namespace) -> None:
    # 加载环境变量(IPAPI_IS_API_KEY 等)
    utils.load_dotenv(args.environment)

    source = os.path.abspath(args.input)
    proxies = load_proxies(source)
    if not proxies:
        logger.error(f"[Rank] no proxies loaded from {source}, exit")
        sys.exit(1)

    logger.info(f"[Rank] loaded {len(proxies)} proxies from {source}")

    metrics = collect_metrics(
        proxies=proxies,
        num_threads=args.num,
        test_url=args.url,
        delay_limit=args.delay,
        ip_library=args.library,
        show_progress=not args.invisible,
    )
    if not metrics:
        logger.error("[Rank] no usable proxies after measurement, exit")
        sys.exit(1)

    logger.info(f"[Rank] usable proxies: {len(metrics)}")

    # ---------- 榜单1:干净家宽榜(仅 isp,国家均衡,延迟取前 N)----------
    clean = [m for m in metrics if m.ip_type == "isp"]
    logger.info(f"[Rank] residential(isp) nodes: {len(clean)}")
    clean_ranklist = balanced_by_country(clean, args.top)
    summarize(clean_ranklist, "clean(home-broadband)")
    save_ranklist(clean_ranklist, os.path.join(PATH, "data", args.clean_output))

    # ---------- 榜单2:速度榜(全部存活,纯延迟升序取前 N)----------
    fast_sorted = sorted(metrics, key=lambda x: x.delay)
    fast_ranklist = fast_sorted[: args.top]
    summarize(fast_ranklist, "fast(low-latency)")
    save_ranklist(fast_ranklist, os.path.join(PATH, "data", args.fast_output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从聚合节点池中筛选干净家宽榜与速度榜")

    parser.add_argument(
        "-i",
        "--input",
        type=str,
        required=False,
        default=os.path.join(PATH, "data", "raw.yaml"),
        help="输入的节点池 yaml 文件路径(由 process.py 预先产出),默认 data/raw.yaml",
    )

    parser.add_argument(
        "-t",
        "--top",
        type=int,
        required=False,
        default=100,
        help="每份榜单保留的节点数量,默认 100",
    )

    parser.add_argument(
        "-d",
        "--delay",
        type=int,
        required=False,
        default=2000,
        help="最大可接受延迟(毫秒),超过视为不可用,默认 2000",
    )

    parser.add_argument(
        "-n",
        "--num",
        type=int,
        required=False,
        default=32,
        help="并发线程数,默认 32",
    )

    parser.add_argument(
        "-u",
        "--url",
        type=str,
        required=False,
        default=DEFAULT_TEST_URL,
        help="延迟测试目标地址",
    )

    parser.add_argument(
        "-l",
        "--library",
        type=str,
        required=False,
        default="ip2location",
        help="IP 信息查询源:ip2location/iplark/ippure/ipinfo/ipapi,默认 ip2location",
    )

    parser.add_argument(
        "-e",
        "--environment",
        type=str,
        required=False,
        default=".env",
        help="环境变量文件名,默认 .env",
    )

    parser.add_argument(
        "--invisible",
        dest="invisible",
        action="store_true",
        default=False,
        help="不显示进度条",
    )

    parser.add_argument(
        "--clean-output",
        type=str,
        required=False,
        default="clash_clean.yaml",
        help="家宽榜输出文件名(保存在 data 目录),默认 clash_clean.yaml",
    )

    parser.add_argument(
        "--fast-output",
        type=str,
        required=False,
        default="clash_fast.yaml",
        help="速度榜输出文件名(保存在 data 目录),默认 clash_fast.yaml",
    )

    main(args=parser.parse_args())
