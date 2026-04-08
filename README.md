# astrbot_plugin_countdown_reminder

群聊倒计时播报插件。可记录考试、比赛、纪念日等重要事件，支持群成员主动查询，也支持每天定时向指定会话自动播报。

## 功能

- 使用中文指令添加、删除、查询倒计时事件
- 支持在 AstrBot WebUI 配置面板中直接管理倒计时事件
- 支持将当前会话加入或移出每日自动播报名单
- 每天按设定时间主动推送倒计时汇总
- 支持时区配置与过期事件显示控制

## 指令

### 用户指令

- `/添加倒计时 <事件名称> <YYYY-MM-DD>`: 添加一个新的倒计时事件
- `/删除倒计时 <事件名称>`: 删除一个已有的倒计时事件
- `/倒计时`: 查看当前所有有效倒计时
- `/倒计时帮助`: 查看插件帮助与使用示例
- `/开启倒计时播报`: 将当前会话加入每日播报名单
- `/关闭倒计时播报`: 将当前会话移出每日播报名单

## 使用示例

- 添加考研倒计时：`/添加倒计时 2026考研 2025-12-20`
- 添加比赛倒计时：`/添加倒计时 数学建模国赛 2026-09-10`
- 添加带空格名称的事件：`/添加倒计时 2026 考研初试 2025-12-20`
- 查询倒计时：`/倒计时`
- 查看帮助：`/倒计时帮助`
- 删除事件：`/删除倒计时 2026考研`
- 开启当前群每日播报：`/开启倒计时播报`
- 关闭当前群每日播报：`/关闭倒计时播报`

## 配置项

配置文件 Schema 位于 [_conf_schema.json](/c:/Users/Lentinel/Documents/GitHub/astrbot-plugin-Countdown-Reminder/_conf_schema.json)，支持在 AstrBot WebUI 可视化配置：

- `events`: 倒计时事件列表，可直接在面板中新增、修改、删除
- `broadcast_time`: 每日播报时间，格式为 `HH:MM`
- `broadcast_targets`: 主动播报目标会话列表，内容为 `unified_msg_origin`
- `timezone`: 倒计时计算和定时任务使用的时区，默认 `Asia/Shanghai`
- `allow_past_events`: 是否允许添加并显示已过期事件

## 数据持久化

本插件支持持久化，机器人重启后数据不会丢失。

- 倒计时事件：保存在 AstrBot 插件配置文件中
- 播报目标会话：保存在 AstrBot 插件配置文件中
- 当日已播报标记：保存在 AstrBot KV 存储中，用于避免同一天重复播报

按 AstrBot 文档约定，插件配置会落盘到 `data/config/<plugin_name>_config.json`。本插件对应文件通常为：

- `data/config/astrbot_plugin_countdown_reminder_config.json`

## 说明

- 倒计时按配置时区的自然日计算，不按小时分钟倒数
- 默认不允许添加过去日期，且查询时不会显示过期事件
- 若开启 `allow_past_events`，则会显示“已经过去 N 天”的事件
- “添加倒计时”和“删除倒计时”已支持带空格的事件名称
- 主动播报依赖 `unified_msg_origin`，建议优先在目标群内执行 `/开启倒计时播报` 完成登记

## 开发与调试

- 插件入口文件： [main.py](/c:/Users/Lentinel/Documents/GitHub/astrbot-plugin-Countdown-Reminder/main.py)
- 插件元数据： [metadata.yaml](/c:/Users/Lentinel/Documents/GitHub/astrbot-plugin-Countdown-Reminder/metadata.yaml)
- 配置 Schema： [_conf_schema.json](/c:/Users/Lentinel/Documents/GitHub/astrbot-plugin-Countdown-Reminder/_conf_schema.json)

建议在 AstrBot 中重载插件后做以下验证：

- 添加 1 到 2 个倒计时事件
- 执行 `/倒计时` 查看返回文案
- 在目标群执行 `/开启倒计时播报`
- 在 WebUI 调整 `broadcast_time` 与 `events`，确认修改可保存
