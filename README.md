# 剧院免费云端放票提醒

正式监控 **Eurotrash、Golden Boy、An Oak Tree（Suranne Jones指定场）、Virginia Woolf（仅伦敦当天）** 的官方票源。Virginia Woolf于2026-10-22按用户要求恢复为当天模式；JCS云端未启用，本地定时任务也已因用户担心Codex额度而暂停。电脑可以关机。只提醒，不登录剧院、不占座、不加购物车、不购买。

## 独立调度与停跑告警

主调度器是私有 **Google Apps Script**：dispatchChecks 时间触发器每五分钟调用 GitHub workflow_dispatch，由标准公共 Linux runner 执行官方查票和浏览器核验。GitHub 原 cron 保留为备用；它曾出现约七小时空档，配置间隔不能当成实际执行频率。

第二个 Google 时间触发器 watchdog 检查各剧目状态的真实读取时间。只有所有仍在演出的剧目都有新的成功读取，才向另一家云服务 **Healthchecks.io** 发健康心跳。任务已排队、绿色工作流、旧成功结果，或只有一部剧更新，都不能反复刷新健康状态。Healthchecks 超过五分钟预期间隔加十分钟宽限未收到新心跳会发送异常邮件，Google 整体停止时仍能告警。

免费服务没有无延迟保证。查看 Actions 实际运行记录、状态中的 last_checked_at 和 Healthchecks 心跳记录；短于检查间隔的变化仍可能错过，发现放票也不保证最终能买到。

## 官方票源与结束时间

| 剧目 | 官方来源 | 监控至（伦敦时间） | 状态文件 |
| --- | --- | --- | --- |
| Eurotrash | Young Vic 官方 Spektrix public Web API；正向信号再次核对普通公开可买座位数 | 2027-01-09 演出结束 | monitor-state.json |
| Golden Boy | Almeida 官方筛选日历实际查询；正向信号打开对应官方售票页核验日期、时间和公开可选票 | 2026-10-31 演出结束 | golden-boy-state.json |
| An Oak Tree / Suranne Jones | The Other Palace官方Spektrix公开票源，仅240703 / 2026-11-15 15:00，正向信号再次排除专属锁座 | 2026-11-15 15:00开演 | an-oak-tree-state.json |
| Who’s Afraid of Virginia Woolf?（仅当天） | @sohoplace官方日历，只筛选Europe/London今天尚未开演的场次；正向信号打开当天官方nLiven票页确认 | 2026-12-19；每天午夜自动切换日期 | virginia-woolf-state.json |
| JCS On-Stage Standing（未启用） | 普通本地浏览器可打开舞台票区；两次GitHub云端Chrome被官网拒绝验证，不能判断库存。仅保留手动诊断，不参加正式心跳 | 需求范围：2026-10-31及之前 | jcs-on-stage-state.json（unknown） |

Eurotrash 官网曾展示 58 项，公开 API 返回 55 场。未返回项包括 Press Night 和 12 月 2 日两场，后两场原因未确认；尚未验证与官网全部场次完全一致。每次重新读取公开列表，不能承诺未公开场次的库存覆盖。

Golden Boy 官方日历表单与脚本使用 WordPress event 11278，官方售票 production 为 8745。2026-10-19 捕捉到 10 月 24 日 14:00 的 Book Tickets / Limited availability，并邮件提前提醒；打开售票页时明确显示 Sold Out，没有宣称确认有票。真实开放按钮内多出的辅助 time 标签已加入回归测试，日期只采用带 datetime 的场次时间。

## 两级提醒与去重

1. **【购票入口变化，余票待核实】**：官方场次出现公开购票链接或票源正向信号就先提醒，随后继续核验。价格和实际余票未确认时明确说明。
2. **【放票提醒】有票了**：再次验证至少一张普通公开可选票/座位后补发确认。只有入口按钮不够；会员、邀请或 Access 专属库存不算普通公开票。Audio Described 或 Relaxed 场次本身不等于专属票。

同一持续信号去重；官方场次确实关闭后重新出现再提醒。提前通知和确认通知分别去重。提醒包含伦敦时间、演出时间、官方直达链接和余票可能随时售出的说明。GitHub issue @提及账户所有者，经其已验证邮箱接收；手机开启 Gmail 新邮件或 GitHub Mentions 通知。

## 故障与时间记录

- 页面错误、验证码、空列表、无法识别的数据、缺少公开座位证据均为 unknown，不能当售罄。
- 连续三次读取失败，单独发“监控异常，不是放票”；恢复后提醒一次。各剧目分开记录。
- last_attempt_at 是实际尝试时间；last_checked_at 只在成功核实本轮状态后更新；last_source_read_at 表示读到了票源信号。last_state_change 不能代替检查时间。
- 独立 watchdog 另检查真实尝试是否超过十五分钟；Healthchecks 监测新的健康结果是否中断。报警演练使用单独、明确标为测试的 check，正式查票持续运行。
- 2027-01-10 自动暂停正式 Healthchecks check 并删除本项目两个 Google 时间触发器，避免演出结束后误报警。

## 私有凭据与停止

公开代码不含个人邮箱、密码或令牌。Google 脚本仅请求联网与无人值守执行，不读取 Gmail。GitHub fine-grained token 仅限本仓库：Actions 写、Contents 读、Issues 写和必需 Metadata 读，2027-01-11 到期。它与 Healthchecks 项目凭据只存 Google 私有 Script Properties，已获用户明确授权；2026-10-21用户要求在同一项目增加以下三个监控，不扩大令牌权限。

完整停止需删除 Google 项目的 dispatchChecks 和 watchdog 两个触发器、暂停 Healthchecks 正式 check，并停用 GitHub 工作流。只停 GitHub 会触发预期故障告警。原来依赖电脑的本地任务保持暂停。

## 验证

运行 python3 -m unittest discover -s tests -v，以及 node --test tests/test_scheduler.cjs。

55 个 Python 测试覆盖官方来源、真实售罄/开放形态、公开座位核验、早期提醒顺序、去重、失败重试和实际读取时间。10 个调度器测试覆盖排队不等于检查、旧结果不能续命、只部分剧目更新不算全体健康、停跑和调度失败。

## 官方依据

- [Young Vic Eurotrash](https://www.youngvic.org/whats-on/eurotrash/)
- [Almeida Golden Boy](https://almeida.co.uk/whats-on/golden-boy/) · [官方退票指引](https://almeida.co.uk/how-to-get-tickets-to-golden-boy/)
- [Google 定时器](https://developers.google.com/apps-script/guides/triggers/installable) · [免费配额](https://developers.google.com/apps-script/guides/services/quotas)
- [GitHub 定时任务可能延迟或丢弃](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)
- [Healthchecks 免费方案](https://healthchecks.io/pricing/) · [故障心跳机制](https://healthchecks.io/docs/)

## 新增监控的范围与负载

每五分钟仍只启动一个工作流，正式运行四项监控。Suranne的日常售罄检查只需少量公开只读请求。Woolf仅检查伦敦当天：未来日期的余票及购票页不核验；官方整轮日历有效但今天没有剩余演出时记录no_performances_today并安静待机，仍属于健康检查。空日历、页面错误与无法验证库存仍记unknown。伦敦午夜和夏冬令时切换由Europe/London处理。此流程在GitHub/Google云端执行，不消耗Codex本地定时额度。JCS诊断代码会用普通Chrome逐场打开舞台票区，但目前未通过云端加载，默认不运行；仅手动勾选jcs_probe可再次诊断，失败作业会明确变红。各剧目独立状态、去重和连续失败告警；新增网站失败不应阻止已完成的其他剧目结果保存。全体健康心跳必须包括每个尚未结束的监控。

只开票区、不改变票数、不点实际座位、不点Update Basket、不接受On-stage Standing Agreement。遇到验证码或未识别票种时记unknown，不把普通席余票或静态£25标签当舞台票。@sohoplace nLiven日历的Low徽标在售罄场次也存在，所以不用它判断有票；官方主页场次计数可能有剧院自身同步/缓存延迟。所有监控都可能漏掉短于检查间隔的退票。演员出席以剧院公告为准。

### JCS实际阻塞（2026-10-21）

在正常Chrome/Xvfb中分别等待16秒与32秒，两次官方日历都返回`We couldn’t verify your browser`（云端日志为ASCII撇号）。未破解验证码、未复制本地cookie或浏览器凭据、未更改指纹规避验证。普通票£25起、舞台票区静态£25标题都不能证明舞台票可买。JCS不加入正式FEEDS，否则它的持续unknown会阻止其他三项续心跳，使后续停跑告警失去区分。只有官方来源在云端真实读取成功后才可启用。2026-10-22本地实测可读取后曾设置JCS本地检查，随后按用户额度顾虑明确暂停；不因此恢复。
