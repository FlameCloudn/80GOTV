"""Steam OpenID 的开始、回调和验证。"""

import ipaddress
import logging
import re
import time
import urllib.parse
import urllib.request
import uuid

from flask import flash, redirect, request, session, url_for

from config import Config
from src.website.web.routing import site_routes

logger = logging.getLogger("80gotv")


STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"


STEAM_OPENID_NS = "http://specs.openid.net/auth/2.0"


STEAM_OPENID_IDENTIFIER = f"{STEAM_OPENID_NS}/identifier_select"


STEAM_AUTH_MAX_AGE = 10 * 60


STEAM_VERIFY_ATTEMPTS = 4


def _get_verified_steam_id(purpose):
    """返回本次 Steam 验证结果；过期或用途不符时返回空。"""
    verified = session.get("steam_verified") or {}
    if verified.get("purpose") != purpose:
        return ""
    if time.time() - float(verified.get("verified_at", 0)) > STEAM_AUTH_MAX_AGE:
        session.pop("steam_verified", None)
        return ""
    steam_id64 = str(verified.get("steam_id64", ""))
    return steam_id64 if steam_id64.isdigit() and len(steam_id64) == 17 else ""


def _is_local_host(host):
    """判断主机名是否属于本机或局域网。"""
    host = (host or "").lower().rstrip(".")
    if (
        host == "localhost"
        or host.endswith((".localhost", ".local"))
        or ("." not in host and ":" not in host)
    ):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _is_local_base_url(value):
    """判断地址是否指向本机或局域网。"""
    return _is_local_host(urllib.parse.urlsplit(value or "").hostname)


def _normalize_base_url(value):
    """整理并检查 Steam 要返回的网站根地址。"""
    parsed = urllib.parse.urlsplit((value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("PUBLIC_BASE_URL 必须是完整的 http 或 https 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("PUBLIC_BASE_URL 不能包含账号、查询参数或片段")
    if parsed.path not in ("", "/"):
        raise ValueError("PUBLIC_BASE_URL 不能包含子路径")

    scheme = parsed.scheme
    if not _is_local_host(parsed.hostname):
        scheme = "https"
    return urllib.parse.urlunsplit((scheme, parsed.netloc, "", "", "")).rstrip("/")


def _steam_base_url():
    """
    固定公网地址优先使用配置值；auto 或本机地址则跟随当前访问地址。
    启用 TRUST_PROXY 后，ProxyFix 会先把 Cloudflare 的外部地址还原到请求中。
    """
    configured = (Config.PUBLIC_BASE_URL or "").strip()
    use_current = not configured or configured.lower() == "auto" or _is_local_base_url(configured)
    return _normalize_base_url(request.host_url if use_current else configured)


def _steam_result_endpoint(purpose):
    """Steam 操作完成后回到用户刚才所在的页面。"""
    return "user_register" if purpose == "register" else "change_password"


def _redirect_after_steam(purpose, message, category="error"):
    flash(message, category)
    endpoint = (
        _steam_result_endpoint(purpose) if purpose in ("register", "recovery") else "user_login"
    )
    return redirect(url_for(endpoint))


def _verify_steam_openid(verify_params):
    """向 Steam 复核 OpenID 回包；国内网络偶发断连时自动重试。"""
    body = urllib.parse.urlencode(verify_params).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, STEAM_VERIFY_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(STEAM_OPENID_URL, data=body, method="POST")
            req.add_header("User-Agent", "80GOTV/1.0")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Steam OpenID 校验连接失败（第 %s/%s 次）：%s",
                attempt,
                STEAM_VERIFY_ATTEMPTS,
                type(exc).__name__,
            )
            if attempt < STEAM_VERIFY_ATTEMPTS:
                time.sleep(0.6 * attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Steam OpenID verification failed without an error")


@site_routes.route("/auth/steam/start")
def steam_auth_start():
    """跳转到 Steam，由 Steam 确认当前用户身份。"""
    purpose = request.args.get("purpose", "")
    if purpose not in ("register", "recovery"):
        return "无效的 Steam 验证用途", 400
    nonce = uuid.uuid4().hex
    try:
        base_url = _steam_base_url()
    except ValueError:
        logger.exception("Steam 返回地址配置无效")
        return _redirect_after_steam(purpose, "Steam 验证地址配置有误，请联系管理员")

    callback_query = urllib.parse.urlencode({"nonce": nonce, "purpose": purpose})
    return_to = f"{base_url}/auth/steam/callback?{callback_query}"
    session["steam_auth"] = {
        "purpose": purpose,
        "nonce": nonce,
        "started_at": time.time(),
        "return_to": return_to,
    }
    params = {
        "openid.ns": STEAM_OPENID_NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": base_url,
        "openid.identity": STEAM_OPENID_IDENTIFIER,
        "openid.claimed_id": STEAM_OPENID_IDENTIFIER,
    }
    return redirect(f"{STEAM_OPENID_URL}?{urllib.parse.urlencode(params)}")


@site_routes.route("/auth/steam/callback")
def steam_auth_callback():
    """校验 Steam 回传，并把已确认的 SteamID 暂存到当前浏览器 session。"""
    pending = session.get("steam_auth") or {}
    purpose = pending.get("purpose") or request.args.get("purpose", "")
    nonce = request.args.get("nonce", "")
    if not pending or nonce != pending.get("nonce"):
        return _redirect_after_steam(purpose, "Steam 验证已失效，请重新操作")
    if time.time() - float(pending.get("started_at", 0)) > STEAM_AUTH_MAX_AGE:
        session.pop("steam_auth", None)
        return _redirect_after_steam(purpose, "Steam 验证已超时，请重新操作")

    if request.args.get("openid.mode") == "cancel":
        session.pop("steam_auth", None)
        return _redirect_after_steam(purpose, "已取消 Steam 验证")

    verify_params = {key: value for key, value in request.args.items() if key.startswith("openid.")}
    returned_to = verify_params.get("openid.return_to", "")
    if not returned_to or returned_to != pending.get("return_to"):
        session.pop("steam_auth", None)
        return _redirect_after_steam(purpose, "Steam 返回地址不一致，请重新操作")

    verify_params["openid.mode"] = "check_authentication"
    try:
        verification = _verify_steam_openid(verify_params)
    except Exception:
        logger.exception("Steam OpenID 校验请求多次重试后仍失败")
        return _redirect_after_steam(purpose, "暂时无法稳定连接 Steam，已自动重试，请稍后再试")

    claimed_id = verify_params.get("openid.claimed_id", "")
    identity = verify_params.get("openid.identity", "")
    match = re.fullmatch(r"https?://steamcommunity\.com/openid/id/(\d{17})", claimed_id)
    verification_values = {}
    for line in verification.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            verification_values[key.strip()] = value.strip()
    valid_response = bool(match) and (
        verification_values.get("is_valid") == "true"
        and verify_params.get("openid.op_endpoint") == STEAM_OPENID_URL
        and identity == claimed_id
    )
    if not valid_response or match is None:
        session.pop("steam_auth", None)
        return _redirect_after_steam(purpose, "Steam 身份验证失败，请重新操作")

    session.pop("steam_auth", None)
    session["steam_verified"] = {
        "purpose": purpose,
        "steam_id64": match.group(1),
        "verified_at": time.time(),
    }
    return _redirect_after_steam(purpose, "Steam 身份验证成功", "success")
