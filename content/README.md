# 内容维护

- `transcripts/`：按场次保存文字稿，每个二级标题对应一个话题。
- `vocabulary.json`：已确认的专名和昵称，支持全局与分场次词单。
- `session-notes.json`：已整理场次的摘要和标签。
- `time-audits.json`：同步时使用的开播时间与录播归属依据。

文字稿格式：

```markdown
<!-- transcript: {"schemaVersion":1,"sessionId":"场次ID","status":"draft","timing":"chunk","source":{"bvid":"录播BV号","page":1,"durationSeconds":录播秒数}} -->
# 直播标题

## 话题标题
[00:10.000 --> 00:25.000] 文字内容。
```

时间相对于指定录播的分 P，段落按顺序排列且不重叠。`status` 为 `draft` 或 `reviewed`；`timing` 为段落定位 `chunk`、模型对齐 `aligned` 或人工核定 `reviewed`。

修改后执行 `npm run build`。转写草稿与校对过程记录保存在本地缓存，发布文件只包含正文及必要元数据。
