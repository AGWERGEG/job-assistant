# v2.0 云端语音 + 文字模拟面试

当前分支：`codex/v2-cloud-voice`。

本轮以云端语音为核心，本地能力为兜底：

```text
浏览器按住说话
→ 本地内存录音
→ 云端 gpt-transcribe 转写
→ 用户核对/编辑文字
→ 普通聊天或逐题面试状态机
→ 云端 gpt-4o-mini-tts 播放
→ 播放失败时浏览器系统朗读
```

原始录音默认不保存，不进入 SQLite、任务快照、上传目录或模型提示。只有用户核对并主动发送/确认后的文字，才会进入普通聊天或模拟面试会话。

## 云端语音

工作台“接入方式与招聘侧栏”中新增 v2 语音设置：

- 云端地址，默认 `https://api.openai.com/v1`
- 云端语音密钥
- 转写模型，默认 `gpt-transcribe`
- 朗读模型，默认 `gpt-4o-mini-tts`
- AI 声音，默认 `marin`
- 是否自动播放新回复

后端接口：

- `POST /api/voice/transcribe`
- `POST /api/voice/speech`

密钥只在本地后端短生命周期子进程的 stdin 中传递，不进入浏览器脚本、URL 或日志。服务端拒绝重定向，限制录音 8 MB，支持 WebM、WAV、MP3、MP4 和 M4A。

OpenAI 官方依据：

- [File transcription](https://developers.openai.com/api/docs/guides/speech-to-text)：`gpt-transcribe`、25 MB 文件上限、WebM 等格式。
- [Text to speech](https://developers.openai.com/api/docs/guides/text-to-speech)：`gpt-4o-mini-tts`、MP3/WAV/PCM 等格式、AI 合成声音披露要求。
- [Audio and speech](https://developers.openai.com/api/docs/guides/audio)：请求式音频 API 与 Realtime 的边界。

当前选择请求式半实时链路，不直接开启全双工 Realtime。原因是产品要求用户先核对转写文字，并且文字模式必须随时可用。

## 本地兜底

可选配置环境变量：

```bash
JOB_ASSISTANT_WHISPER_BIN=/path/to/whisper-cli
JOB_ASSISTANT_WHISPER_MODEL=/path/to/ggml-model.bin
JOB_ASSISTANT_FFMPEG_BIN=/path/to/ffmpeg
```

云端转写失败且本地工具完整时，后端自动使用 `whisper.cpp`。播放失败时浏览器使用 `speechSynthesis`。两种本地兜底都不保存原始音频。

## 逐题模拟面试

新增幂等迁移表：

- `interview_sessions`
- `interview_turns`

Store schema 从 9 升到 10。旧的 `interview_prep` / `interview_review` 任务不转换为会话，防止历史 AI 草稿被误认为真实回答。

状态：

```text
starting → generating_question → awaiting_answer
       → advancing → generating_question
       → generating_recap → completed

任意进行中状态 → paused → resume
任意进行中状态 → ending → generating_recap
模型失败 → failed → retry
```

每轮只有一个问题。用户回答必须勾选确认后才写入 `interview_turns.answer_text`。跳过题目不生成回答。已确认回答才会进入下一题和复盘提示词。

面试模型任务使用独立 `interview` worker 通道，不占普通聊天或简历后台通道：

- `interview_question`
- `interview_recap`

默认 worker 现在至少保留三个槽位：chat、interview、background。

工作台“面试”页签提供：

- 岗位和已验收简历选择
- 模拟目标
- 逐题问题与回答确认
- 语音回答转写
- 暂停、继续、跳过、结束并复盘
- 已确认问答记录
- 结构化复盘

## 事实边界

- 历史 AI 草稿不是个人事实。
- 不把模拟回答自动写入长期档案。
- 不自动记录真实面试完成、offer、入职或录用概率。
- 不根据时长、沉默、语气、表情预测招聘结果。
- 不补写用户没有提供的数字、工具、职责、协作对象或成果。

## 验证

当前回归：

- Python：97 项
- 工作台与扩展 JavaScript：58 项

新增测试覆盖云端转写/TTS、密钥隔离、音频不落盘、云端失败本地兜底、语音 UI、面试会话幂等、回答确认、岗位隔离、暂停/恢复/跳过/结束、导出和删除。

尚未宣称完成的验收：真实 OpenAI 付费语音调用、真实麦克风环境、Edge/Chrome 权限提示、whisper.cpp 本地模型下载和中文语音质量。这些需要后续人工验收。
