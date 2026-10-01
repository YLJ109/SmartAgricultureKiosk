"""微信扫码上传：手机拍完照，直接传到这台一体机上。

为什么不是"微信 JS-SDK / 公众号"那套
------------------------------------
那需要公众号 AppID、网页授权域名、HTTPS 证书，村里一台离线终端不具备这些条件。
真正能落地的是：一体机在局域网里提供一张极简上传页，二维码里放的就是这张页面的地址。
农户用微信「扫一扫」打开它（微信内置浏览器能正常打开局域网 http 页面），拍完照直接回传。

流程
----
1. 一体机进入取景态时调 `POST /api/recognize/mobile/session`，拿到一次性 token 和上传页地址；
2. 把地址渲染成二维码显示出来，同时开始轮询 `/pending`；
3. 手机扫码打开 `/m?t=token`，拍照 -> `POST /mobile/upload`；
4. 一体机轮询到图片后，把它当作一次普通上传交给 `/api/recognize`（channel=qrcode）识别。

安全
----
token 一次性、5 分钟过期、只能取走自己会话里的图片；上传接口只认 token，不要求登录态
（手机端拿不到一体机的登录态）。会话数据放内存：单实例部署够用，多实例要换 Redis。
"""

from __future__ import annotations

import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse
from loguru import logger

from app.config import settings
from app.core.auth import OptionalUser

router = APIRouter(tags=["mobile"])

#: 会话有效期（秒）。太短老人来不及扫，太长则一台机器上会堆一堆废弃会话。
SESSION_TTL = 300
#: 轮询间隔建议值，随 session 一起返回，前端据此设定时器
POLL_INTERVAL_MS = 2000

_SUBDIR = "mobile"


@dataclass
class MobileSession:
    token: str
    created_at: float
    image_path: Path | None = None
    claimed: bool = False
    field: dict = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > SESSION_TTL


_sessions: dict[str, MobileSession] = {}


def _gc() -> None:
    """清掉过期会话，并顺手删掉没被取走的图片文件，避免 uploads 越堆越多。"""
    for token, sess in list(_sessions.items()):
        if not sess.expired:
            continue
        _sessions.pop(token, None)
        if sess.image_path and sess.image_path.exists():
            sess.image_path.unlink(missing_ok=True)


def _lan_ip() -> str:
    """取本机在局域网里的地址（手机要能用它访问到这台一体机）。

    先用一次不真正发包的 UDP connect 让内核挑出默认出口网卡 —— 比遍历网卡可靠。
    但这一步在装了 VPN / Docker / VMware 的机器上会挑到隧道口或容器网段，
    手机根本连不通。所以把所有候选地址按"越像家用局域网越优先"排一遍：
    192.168.x > 10.x > 172.16~31（Docker 默认的 172.17 因此排最后）。
    """
    candidates: list[str] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("223.5.5.5", 80))  # 不真的发包，只为让内核选出口网卡
        candidates.append(sock.getsockname()[0])
    except Exception:
        pass
    finally:
        sock.close()

    try:
        candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass

    def score(ip: str) -> int:
        if ip.startswith("127."):
            return -1
        if ip.startswith("192.168."):
            return 3
        if ip.startswith("10."):
            return 2
        if ip.startswith("172."):
            try:
                second = int(ip.split(".")[1])
            except (IndexError, ValueError):
                return -1
            return 1 if 16 <= second <= 31 else -1
        return -1

    best = max(candidates, key=score, default="")
    return best if score(best) > 0 else "127.0.0.1"


def _mobile_dir() -> Path:
    path = settings.upload_path / _SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/api/recognize/mobile/session")
async def create_session(user: OptionalUser) -> dict:
    """开一次扫码上传会话，返回二维码里要放的地址。"""
    _gc()
    token = secrets.token_urlsafe(18)
    _sessions[token] = MobileSession(token=token, created_at=time.time())

    host = _lan_ip()
    url = f"http://{host}:{settings.port}/m?t={token}"
    logger.info("已开扫码上传会话 {}，上传页 {}", token[:6], url)
    return {
        "token": token,
        "url": url,
        "expires_in": SESSION_TTL,
        "poll_interval_ms": POLL_INTERVAL_MS,
        # 前端提示语里要区分"局域网直连"和"仅本机可访问"，127.0.0.1 时手机其实扫不通
        "reachable": host != "127.0.0.1",
    }


@router.post("/api/recognize/mobile/upload")
async def mobile_upload(
    token: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    """手机端上传入口。只认 token，不需要登录态。"""
    _gc()
    sess = _sessions.get(token)
    if sess is None or sess.expired:
        return {"ok": False, "message": "二维码已过期，请在一体机上重新生成"}

    ext = Path(file.filename or "").suffix.lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return {"ok": False, "message": "只支持 JPG / PNG / WEBP / BMP 图片"}

    target = _mobile_dir() / f"{uuid4().hex}{ext}"
    size = 0
    with target.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.max_upload_bytes:
                fh.close()
                target.unlink(missing_ok=True)
                return {"ok": False, "message": f"图片不能超过 {settings.max_upload_mb}MB"}
            fh.write(chunk)
    await file.close()

    # 同一会话重复上传：旧的没被取走就换掉并删除，只保留最新一张
    if sess.image_path and sess.image_path.exists():
        sess.image_path.unlink(missing_ok=True)
    sess.image_path = target
    sess.claimed = False

    logger.info("手机端上传成功：{}（{} 字节）", target.name, size)
    return {"ok": True, "message": "照片已传到一体机，请看大屏"}


@router.get("/api/recognize/mobile/pending")
async def mobile_pending(token: str = Query(...)) -> dict:
    """一体机轮询：有没有手机刚传上来的照片。

    取走即删除本地文件（图片已经交给识别流程落盘了），避免同一张图被反复识别。
    """
    _gc()
    sess = _sessions.get(token)
    if sess is None or sess.expired:
        return {"ready": False, "expired": True}
    if sess.image_path is None or sess.claimed:
        return {"ready": False, "expired": False}

    sess.claimed = True
    rel = sess.image_path.relative_to(settings.upload_path.parent).as_posix()
    return {"ready": True, "expired": False, "image_url": "/" + rel}


@router.get("/m", response_class=HTMLResponse)
async def mobile_page(t: str = Query("")) -> HTMLResponse:
    """手机端上传页。

    整页内联，不依赖前端构建产物：手机打开的是后端端口，
    这样上传接口与页面同源，不用操心 CORS，也不受一体机前端是否在跑的影响。
    """
    return HTMLResponse(_page(t))


def _page(token: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="format-detection" content="telephone=no">
<title>拍照上传 · 智慧农业一体机</title>
<style>
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
  body {{
    margin: 0; min-height: 100vh; padding: 24px 18px 40px;
    font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: linear-gradient(170deg, #eaf6ee 0%, #ffffff 46%, #f6fbf7 100%);
    color: #16201b;
  }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  p.sub {{ margin: 0 0 22px; color: #5b6b62; font-size: 15px; line-height: 1.6; }}
  ol {{ margin: 0 0 22px; padding-left: 20px; color: #3d4a43; font-size: 15px; line-height: 1.9; }}
  .btn {{
    display: block; width: 100%; padding: 20px; margin-bottom: 14px;
    border: none; border-radius: 16px; font-size: 19px; font-weight: 700;
    color: #fff; background: linear-gradient(135deg, #2e9e4f, #247f3f);
    box-shadow: 0 10px 24px rgba(36, 127, 63, .28);
  }}
  .btn.ghost {{
    color: #247f3f; background: #fff;
    border: 2px solid #cfe6d7; box-shadow: 0 6px 16px rgba(22, 32, 27, .06);
  }}
  .btn:active {{ transform: scale(.985); }}
  .btn[disabled] {{ opacity: .55; }}
  #status {{
    margin-top: 18px; padding: 16px; border-radius: 14px; font-size: 16px;
    line-height: 1.6; display: none; white-space: pre-wrap;
  }}
  #status.ok {{ display: block; background: #e8f7ed; color: #1d6b36; }}
  #status.err {{ display: block; background: #fdeceb; color: #a3241c; }}
  #status.busy {{ display: block; background: #eef4ff; color: #1a5fb4; }}
  #preview {{ width: 100%; border-radius: 14px; margin-top: 18px; display: none; }}
  .foot {{ margin-top: 26px; color: #8a978f; font-size: 13px; text-align: center; }}
</style>
</head>
<body>
  <h1>把照片传到一体机</h1>
  <p class="sub">拍一张病叶照片，传过去后大屏会自动开始识别。</p>
  <ol>
    <li>把病叶平放在白纸或干净地面上</li>
    <li>让病斑占画面一半以上，光线均匀</li>
    <li>拍完点下面的按钮上传</li>
  </ol>

  <button class="btn" id="shoot" type="button">拍照上传</button>
  <button class="btn ghost" id="pick" type="button">从相册选择</button>
  <input id="cam" type="file" accept="image/*" capture="environment" hidden>
  <input id="album" type="file" accept="image/*" hidden>

  <img id="preview" alt="预览">
  <div id="status"></div>
  <div class="foot">智慧农业多语言一体机服务系统</div>

<script>
(function () {{
  var TOKEN = {token!r};
  var statusEl = document.getElementById('status');
  var preview = document.getElementById('preview');
  var busy = false;

  function say(kind, text) {{
    statusEl.className = kind;
    statusEl.textContent = text;
  }}

  if (!TOKEN) {{
    say('err', '这个链接不完整，请回到一体机上重新扫码。');
    document.getElementById('shoot').disabled = true;
    document.getElementById('pick').disabled = true;
    return;
  }}

  async function upload(file) {{
    if (busy) return;
    busy = true;
    say('busy', '正在上传，请不要关掉这个页面…');
    preview.src = URL.createObjectURL(file);
    preview.style.display = 'block';

    var form = new FormData();
    form.append('token', TOKEN);
    form.append('file', file, 'phone.jpg');

    try {{
      var resp = await fetch('/api/recognize/mobile/upload', {{ method: 'POST', body: form }});
      var data = await resp.json();
      if (data.ok) {{
        say('ok', '上传成功！请回到一体机大屏，正在为你识别。\\n同一张照片不用重复上传。');
      }} else {{
        say('err', data.message || '上传失败，请重试。');
      }}
    }} catch (e) {{
      say('err', '网络中断，上传失败。请确认手机和一体机连的是同一个 WiFi 后重试。');
    }} finally {{
      busy = false;
    }}
  }}

  function bind(inputId, buttonId) {{
    var input = document.getElementById(inputId);
    document.getElementById(buttonId).addEventListener('click', function () {{ input.click(); }});
    input.addEventListener('change', function () {{
      var file = input.files && input.files[0];
      input.value = '';
      if (file) upload(file);
    }});
  }}

  bind('cam', 'shoot');
  bind('album', 'pick');
}})();
</script>
</body>
</html>
"""
