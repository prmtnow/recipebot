import os, sys, time

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from app.extractor import Extractor

video = open(os.path.expandvars(r"%TEMP%\flower.mp4"), "rb").read()
print(f"video {len(video)} bytes")
ex = Extractor(os.environ["GEMINI_API_KEY"])
t0 = time.time()
r = ex.extract(video, "video/mp4")
dt = time.time() - t0
print(f"{dt:.1f}s cost=${r.cost_usd:.4f} error={r.error}")
print((r.recipe or "")[:600])
