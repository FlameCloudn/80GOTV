"""Find and run the CSDA command-line parser against validated Demo input."""

import json
import os
import shutil
import subprocess
import tempfile

from src.website.runtime.storage import SOURCE_ROOT


def find_csda():
    """查找 csda 可执行文件路径"""
    path = os.environ.get("CSDA_PATH", "csda")
    if shutil.which(path):
        return path
    for candidate in ["csda.exe", "csda"]:
        if shutil.which(candidate):
            return candidate
    if SOURCE_ROOT.parent.name == "products":
        folder = SOURCE_ROOT.parent.parent / "state/toolchain/bin"
        for candidate in ["csda.exe", "csda"]:
            full = os.path.join(folder, candidate)
            if os.path.isfile(full):
                return full
    return None


def run_analysis(demo_path, output_dir=None):
    """
    运行 csda 分析 demo 文件，返回解析后的 JSON 数据
    异常: RuntimeError（csda 未安装） / FileNotFoundError / subprocess.TimeoutExpired
    """
    csda_path = find_csda()
    if not csda_path:
        raise RuntimeError(
            "csda 未找到。请从 https://github.com/akiver/cs-demo-analyzer/releases "
            "下载 csda 并添加到 PATH，或设置 CSDA_PATH 环境变量"
        )

    if not os.path.isfile(demo_path):
        raise FileNotFoundError(f"Demo 文件不存在: {demo_path}")

    tmpdir = None
    if output_dir is None:
        tmpdir = tempfile.mkdtemp(prefix="csda_")
        output_dir = tmpdir

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(demo_path))[0]
    # 每次独立空目录兼容旧版 csda（只接受目录），也不可能误读上次生成的 JSON。
    run_output_dir = tempfile.mkdtemp(prefix=f"csda_{base}_", dir=output_dir)
    json_path = os.path.join(run_output_dir, f"{base}.json")

    try:
        source = os.environ.get("CSDA_SOURCE", "valve")
        result = subprocess.run(
            [
                csda_path,
                "-demo-path",
                demo_path,
                "-output",
                run_output_dir,
                "-format",
                "json",
                "-source",
                source,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip() or "未知错误"
            raise RuntimeError(f"csda 分析失败 (exit {result.returncode}): {stderr}")

        if not os.path.isfile(json_path):
            generated = [
                os.path.join(run_output_dir, name)
                for name in os.listdir(run_output_dir)
                if name.endswith(".json")
            ]
            if len(generated) != 1:
                raise RuntimeError("csda 未生成唯一的本次 JSON 输出，请检查 demo 文件是否有效")
            json_path = generated[0]

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise RuntimeError("csda 生成的 JSON 格式无效")

        return data

    except subprocess.TimeoutExpired:
        raise RuntimeError("csda 分析超时（超过 300 秒）")
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


def validate_demo(demo_path):
    """验证 Demo 文件格式"""
    if not os.path.exists(demo_path):
        return False, "文件不存在"
    if not demo_path.lower().endswith(".dem"):
        return False, "文件格式错误，需要 .dem 文件"
    return True, "文件有效"
