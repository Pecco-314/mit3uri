# 本地转写

使用 Qwen3-ASR、Silero VAD 和 Qwen3-ForcedAligner，按自然停顿分段，歌曲单独处理，结果供人工校对。

当前实现依赖 Apple Silicon、Python 3.12+ 和 MLX。安装环境与模型：

```sh
sh scripts/asr/setup.sh
.venv-asr/bin/python scripts/asr/download_model.py --output .cache/asr/models/Qwen3-ASR-1.7B-8bit
HF_HOME=.cache/asr/huggingface .venv-asr/bin/python scripts/asr/download_alignment_models.py
```

选择完整录播，下载音频后转写：

```sh
.venv-asr/bin/python scripts/asr/download_audio.py BV号 --output .cache/asr/场次ID
HF_HOME=.cache/asr/huggingface HF_HUB_OFFLINE=1 .venv-asr/bin/python scripts/asr/transcribe_natural.py \
  --session 场次ID --audio 音频路径 --regions 配置路径 --output .cache/asr/场次ID/transcript
```

配置文件保存在本地缓存，基本格式为 `{"sessionId":"场次ID","songs":[]}`。歌曲填入 `songs`，每项包含 `id`、`start`、`end`、`language`，起止时间以音频秒数计。

词单位于 `content/vocabulary.json`。转写输出 `raw.txt`、`raw.json` 和含时间对齐信息的 `pipeline.json`；人工整理后按 [内容格式](../../content/README.md) 保存文字稿。

模型、音频和转写结果保存在 `.cache/asr/`，不上传到仓库。
