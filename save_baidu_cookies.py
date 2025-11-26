#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一脚本：获取百度网盘 Cookies（支持扫码/账号登录）并可选写入 GitHub Secrets。

功能：
  - 通过 Playwright 打开真实浏览器登录百度网盘，提取 Cookie：
      * BAIDU_COOKIES：仅 BDUSS 与 STOKEN（项目最小必需）
      * BAIDU_COOKIES_FULL：全部 cookie 合并（优先 pan.baidu.com，正确格式拼接）
  - 将上述变量写入本地 baidu_cookies.env
  - 可选：使用 gh CLI 将变量写入 GitHub 仓库 Secrets

依赖：
  - pip install playwright
  - python -m playwright install
  - 写 Secrets 需要 GitHub CLI：brew install gh && gh auth login

示例：
  - 获取并写入 Secrets：
      python save_baidu_cookies.py --repo owner/repo
  - 仅获取并写 env：
      python save_baidu_cookies.py
  - 从已有 env 写 Secrets（不启浏览器）：
      python save_baidu_cookies.py --repo owner/repo --from-env --env baidu_cookies.env
  - 只写最小或全量 Secrets：
      python save_baidu_cookies.py --repo owner/repo --min-only
      python save_baidu_cookies.py --repo owner/repo --full-only
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional, Tuple, Dict

try:
    from logger import get_logger, setup_logging
except ImportError:
    # 日志模块不可用时，提供简单的 fallback
    def get_logger():
        import logging

        return logging.getLogger(__name__)

    def setup_logging(*args, **kwargs):
        pass


if TYPE_CHECKING:
    try:
        from playwright.sync_api import sync_playwright, BrowserContext  # type: ignore  # noqa: F401
    except ImportError:
        pass  # Optional dependency

try:
    from playwright.sync_api import sync_playwright, BrowserContext  # type: ignore

    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

USER_DATA_DIR = str(Path.home() / ".baidu_pan_profile")  # 持久化用户目录
OUTPUT_ENV = "baidu_cookies.env"  # 输出 env 片段文件
LOGIN_URL = "https://pan.baidu.com/"

# 按域优先级选取同名 Cookie，越靠前优先级越高
PREFERRED_DOMAINS = (
    "pan.baidu.com",
    ".pan.baidu.com",
    ".baidu.com",
    "baidu.com",
)

# 打印与排序时常见关键 Cookie 的优先顺序（存在则按此顺序置前）
PREFERRED_ORDER = [
    "BDUSS",
    "STOKEN",
    "BDUSS_BFESS",
    "STOKEN_BFESS",
    "BDCLND",
    "BAIDUID",
    "PANWEB",
    "H_PS_PSSID",
    "BDORZ",
    "BDRCVFR",
]


def load_config(config_path: Path = Path("config.json")) -> Dict:
    """从配置文件加载配置，带错误处理"""
    try:
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"配置文件格式错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"读取配置文件失败: {e}")
        sys.exit(1)


def update_secret_shareurl_from_config(repo: str, name: str):
    """从 config.json 读取 share_urls 并写入 GitHub Secrets"""
    config = load_config()
    urls = config.get("share_urls", [])
    if not urls:
        print("配置文件中未找到 share_urls")
        sys.exit(1)
    share_urls = "\n".join([s for s in urls if isinstance(s, str) and s.strip()])
    ensure_gh()
    set_secret(repo, name, share_urls)


def update_secret_cookie_from_config(repo: str, name: str):
    """从 config.json 读取 cookies 并写入 GitHub Secrets"""
    config = load_config()
    cookies: str = config.get("cookies", "")
    if not cookies:
        print("配置文件中未找到 cookies")
        sys.exit(1)
    ensure_gh()
    set_secret(repo, name, cookies)


def find_cookie(
    cookies: Iterable[dict], name: str, domains=PREFERRED_DOMAINS
) -> Optional[str]:
    """在 cookies 集合中查找指定名称且域名匹配的 cookie 值"""
    best_value = None
    best_rank = -1
    for c in cookies:
        if c.get("name") != name:
            continue
        domain = c.get("domain", "")
        # 计算域匹配优先级
        rank = -1
        for i, d in enumerate(domains):
            if d in domain:
                rank = len(domains) - i
                break
        if rank > best_rank:
            best_rank = rank
            best_value = c.get("value")
    return best_value


def mask_token(token: str, head: int = 4, tail: int = 4) -> str:
    """遮罩敏感 token，仅显示前后少量字符"""
    if not token:
        return token
    if len(token) <= head + tail:
        return "*" * len(token)
    return f"{token[:head]}***{token[-tail:]}"


def wait_for_cookies(ctx, timeout_sec: int = 600):
    """轮询等待直到获得 BDUSS 与 STOKEN 或超时"""
    deadline = time.time() + timeout_sec
    bduss, stoken = None, None
    while time.time() < deadline:
        cookies = ctx.cookies()
        bduss = find_cookie(cookies, "BDUSS")
        stoken = find_cookie(cookies, "STOKEN")
        if bduss and stoken:
            return bduss, stoken, cookies
        time.sleep(2)
    return bduss, stoken, ctx.cookies()


def build_cookie_map(cookies: Iterable[dict], domains=PREFERRED_DOMAINS) -> dict:
    """将 cookies 合并为 name -> value，按域优先级去重（优先 pan.baidu.com）"""
    merged: dict[str, tuple[int, str]] = {}
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain", "")
        if not name or value is None:
            continue
        # 域优先级
        rank = 0
        for i, d in enumerate(domains):
            if d in domain:
                rank = len(domains) - i
                break
        prev = merged.get(name)
        if (prev is None) or (rank > prev[0]):
            merged[name] = (rank, value)
    # 去掉 rank，仅保留值
    return {k: v for k, (_, v) in merged.items()}


def build_cookie_string(cookie_map: dict) -> str:
    """将 {name: value} 转为 "name=value; name2=value2" 格式。先 preferred 再字母序。"""
    items = []
    remaining = dict(cookie_map)
    for key in PREFERRED_ORDER:
        if key in remaining:
            items.append(f"{key}={remaining.pop(key)}")
    for key in sorted(remaining.keys()):
        items.append(f"{key}={remaining[key]}")
    return "; ".join(items)


def ensure_gh() -> None:
    """检查 GitHub CLI 是否可用，不可用则退出"""
    try:
        subprocess.run(
            ["gh", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except FileNotFoundError:
        print("❌ gh CLI 未找到。请先安装并登录：\n  brew install gh\n  gh auth login")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 检查 gh CLI 时出错: {e}")
        sys.exit(1)


def set_secret(repo: str, name: str, value: str) -> None:
    """设置 GitHub Secret，带错误处理"""
    if not value:
        print(f"⚠️  跳过 {name}：值为空")
        return
    try:
        print(f"设置 {name} 到 {repo}...")
        subprocess.run(
            ["gh", "secret", "set", name, "-R", repo, "--body", value],
            check=True,
            capture_output=True,
        )
        print(f"✅ {name} 设置成功")
    except subprocess.CalledProcessError as e:
        print(f"❌ 设置 {name} 失败: {e}")
        if e.stderr:
            print(f"错误详情: {e.stderr.decode('utf-8', errors='ignore')}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 设置 {name} 时发生错误: {e}")
        sys.exit(1)


def read_env_values(env_path: Path) -> Dict[str, str]:
    """从 env 文件读取 cookie 值，带错误处理"""
    try:
        if not env_path.exists():
            raise FileNotFoundError(f"找不到 env 文件: {env_path}")
        text = env_path.read_text(encoding="utf-8")

        def extract(key: str) -> str:
            m = re.search(rf'^{re.escape(key)}="(.*)"\s*$', text, re.MULTILINE)
            return m.group(1) if m else ""

        return {
            "BAIDU_COOKIES": extract("BAIDU_COOKIES"),
            "BAIDU_COOKIES_FULL": extract("BAIDU_COOKIES_FULL"),
        }
    except Exception as e:
        print(f"读取 env 文件失败: {e}")
        sys.exit(1)


def write_env_file(env_path: Path, cookies_min: str, cookies_full: str) -> None:
    """将 cookies 写入 env 文件，带错误处理"""
    try:
        content = (
            f'BAIDU_COOKIES="{cookies_min}"\nBAIDU_COOKIES_FULL="{cookies_full}"\n'
        )
        env_path.write_text(content, encoding="utf-8")
        print(f"✅ Cookies 已写入: {env_path}")
    except Exception as e:
        print(f"❌ 写入 env 文件失败: {e}")
        sys.exit(1)


def mask_cookie_string(cookie_str: str, show_length: int = 50) -> str:
    """掩码 cookie 字符串，只显示前后部分"""
    if not cookie_str:
        return cookie_str
    if len(cookie_str) <= show_length * 2:
        return "*" * len(cookie_str)
    return f"{cookie_str[:show_length]}...({len(cookie_str)} chars)...{cookie_str[-show_length:]}"


def do_browser_login_and_extract(
    headless: bool = False, show_full_cookie: bool = False
) -> Tuple[str, str]:
    """通过浏览器登录并提取 cookies，返回 (cookies_min, cookies_full)"""
    if not PLAYWRIGHT_AVAILABLE:
        print(
            "Playwright 未安装。请先执行：\n  pip install playwright\n  python -m playwright install"
        )
        sys.exit(1)

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        # 如果顶部导入失败，这里也会失败，但 PLAYWRIGHT_AVAILABLE 检查应该已经捕获
        raise RuntimeError("Playwright 未安装") from None

    print("即将启动浏览器，请在弹出窗口中完成百度网盘登录（可扫码登录）。")
    print(
        "登录成功后脚本会自动抓取 Cookie（含 BDUSS/STOKEN 及全部 Cookie）。最多等待 10 分钟..."
    )

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                USER_DATA_DIR,
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.new_page()
            page.goto(LOGIN_URL, wait_until="load")

            bduss, stoken, cookies = wait_for_cookies(ctx, timeout_sec=600)

            # 即使未获取到最小必需项，也构建全量 Cookie
            cookie_map = build_cookie_map(cookies)
            cookies_full_str = build_cookie_string(cookie_map)
            cookies_min_str = (
                f"BDUSS={bduss}; STOKEN={stoken}" if bduss and stoken else ""
            )

            if not (bduss and stoken):
                print("\n⚠️  未能获取到完整的最小必需 Cookie（BDUSS/STOKEN）。")
                print(
                    "建议：\n  - 登录后刷新页面或点击右上角登录\n  - 扫码通常更稳\n  - 重新运行脚本重试"
                )
            else:
                print("\n✅ 已获取最小必需 Cookie（请妥善保管，不要泄露）：")
                print(f"  BDUSS  = {mask_token(bduss)}")
                print(f"  STOKEN = {mask_token(stoken)}")

            if show_full_cookie:
                print("\n完整 Cookie（含全部 name=value；请谨慎保管）：")
                print(cookies_full_str)
            else:
                print("\n完整 Cookie（已掩码，使用 --show-full-cookie 查看完整内容）：")
                print(mask_cookie_string(cookies_full_str))

            try:
                ctx.close()
            except Exception:
                pass

        return cookies_min_str, cookies_full_str
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 浏览器登录过程中发生错误: {e}")
        sys.exit(1)


def main() -> None:
    """主函数：解析参数并执行相应操作"""
    ap = argparse.ArgumentParser(
        description="获取百度网盘 Cookies 并可选写入 GitHub Secrets 和本地 env 文件"
    )
    ap.add_argument("--repo", help="目标仓库 owner/repo，提供则写入 Secrets")
    ap.add_argument(
        "--headless",
        action="store_true",
        help="无头模式运行浏览器（不推荐，扫码不便）",
    )
    ap.add_argument(
        "--from-env",
        action="store_true",
        help="从已有 env 文件读取 cookies 并写入 Secrets（不启动浏览器）",
    )
    ap.add_argument(
        "--env",
        type=str,
        default=OUTPUT_ENV,
        help=f"env 文件路径（默认: {OUTPUT_ENV}）",
    )
    ap.add_argument(
        "--min-only",
        action="store_true",
        help="仅写入最小必需 Cookie（BAIDU_COOKIES）到 Secrets",
    )
    ap.add_argument(
        "--full-only",
        action="store_true",
        help="仅写入完整 Cookie（BAIDU_COOKIES_FULL）到 Secrets",
    )
    ap.add_argument(
        "--no-env-file",
        action="store_true",
        help="不写入本地 env 文件",
    )
    ap.add_argument(
        "--show-full-cookie",
        action="store_true",
        help="显示完整的 cookie 字符串（默认会掩码显示）",
    )
    args = ap.parse_args()

    # 处理 --from-env 模式
    if args.from_env:
        if not args.repo:
            print("❌ --from-env 需要配合 --repo 使用")
            sys.exit(1)
        env_path = Path(args.env)
        try:
            env_values = read_env_values(env_path)
            ensure_gh()

            if args.min_only:
                if env_values["BAIDU_COOKIES"]:
                    set_secret(args.repo, "BAIDU_COOKIES", env_values["BAIDU_COOKIES"])
                else:
                    print("❌ env 文件中未找到 BAIDU_COOKIES")
                    sys.exit(1)
            elif args.full_only:
                if env_values["BAIDU_COOKIES_FULL"]:
                    set_secret(
                        args.repo,
                        "BAIDU_COOKIES_FULL",
                        env_values["BAIDU_COOKIES_FULL"],
                    )
                else:
                    print("❌ env 文件中未找到 BAIDU_COOKIES_FULL")
                    sys.exit(1)
            else:
                # 默认写入两个
                if env_values["BAIDU_COOKIES"]:
                    set_secret(args.repo, "BAIDU_COOKIES", env_values["BAIDU_COOKIES"])
                if env_values["BAIDU_COOKIES_FULL"]:
                    set_secret(
                        args.repo,
                        "BAIDU_COOKIES_FULL",
                        env_values["BAIDU_COOKIES_FULL"],
                    )
            print("✅ Secrets 写入完成。")
        except Exception as e:
            print(f"❌ 处理失败: {e}")
            sys.exit(1)
        return

    # 处理浏览器登录模式
    cookies_min, cookies_full = do_browser_login_and_extract(
        headless=args.headless, show_full_cookie=args.show_full_cookie
    )

    if not cookies_min:
        print("❌ 未能获取到最小必需 Cookie，退出")
        sys.exit(1)

    # 写入本地 env 文件
    if not args.no_env_file:
        env_path = Path(args.env)
        write_env_file(env_path, cookies_min, cookies_full)

    # 写入 GitHub Secrets
    if args.repo:
        ensure_gh()
        try:
            if args.min_only:
                set_secret(args.repo, "BAIDU_COOKIES", cookies_min)
            elif args.full_only:
                set_secret(args.repo, "BAIDU_COOKIES_FULL", cookies_full)
            else:
                # 默认写入两个
                set_secret(args.repo, "BAIDU_COOKIES", cookies_min)
                set_secret(args.repo, "BAIDU_COOKIES_FULL", cookies_full)
            print("✅ Secrets 写入完成。")
        except Exception as e:
            print(f"❌ 写入 Secrets 失败: {e}")
            sys.exit(1)


if __name__ == "__main__":
    # main()
    update_secret_shareurl_from_config(
        repo="Jack-261108/transfershare", name="SHARE_URLS"
    )
