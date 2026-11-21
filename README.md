# 经营归因分析系统

当前源码推进到「数据导入、多轮探查、持久任务与模型预算」阶段，尚未完成全部 PRD，也尚未在远程环境进行集成验收。

## 已编写的能力

- 加法、LMDI、精确 Shapley、比率贡献分摊，两个冻结 PRD 样例。
- 私有 CSV/JSON 日聚合导入、内容摘要去重、不可变版本；双场景 90 天合成数据。
- 等长比较期、渠道/区域/品类/客群筛选和下钻、跨轮范围继承及返回上一级。
- PostgreSQL 持久任务、幂等提交、单会话串行、租约与重领、旧 worker 写入隔离、取消、SSE 断线回放。
- DeepSeek 结构化意图规划；服务端再次校验范围；模型不产生金额结论、不执行生成代码。
- 累计 25 元预算账本、调用前预留、已知用量保守估算、未知用量保留预留额度。
- 登录、Cookie、CSRF、账号/业务权限与所有权检查、操作审计。
- React 工作台、数据导入、任务记录、规则/模型追问、贡献图表、当前快照模拟、Markdown 导出、管理员预算查看。

## 验证与剩余工作

本机仅使用已有 Python / Node / Docker CLI 进行纯函数和静态检查；没有安装项目依赖、启动 Docker/业务服务、调用付费 API。

24 项纯函数测试已通过，覆盖数值守恒、零/负值、数据去重/缺口、精确小数、范围继承、非法条件、快照模拟与预算估算。已编写 13 项 PostgreSQL 集成测试，覆盖权限、幂等、取消、过期租约、撤权和预算异常；**集成测试尚未执行**。

前端 TypeScript 编译、浏览器验收、PostgreSQL 迁移与并发联调、容器构建、真实 DeepSeek 调用，仍需远程环境。依赖锁文件、镜像摘要、数据库 RLS、运行/迁移账号分离和备份恢复尚未完成。当前 Compose 是远程开发集成配置，不是已加固的生产部署方案。

仍待实现：动态指标管理、订单级去重、独立 Linux/gVisor 沙箱、统计检验与多假设验证、事件和历史案例检索、历史收益区间、PDF/Excel 导出、报告协作发布、简报订阅、完整角色管理。界面明确显示统计尚未执行，不把数学分解当作因果结论。

## 只在远程环境运行

服务器尚未选定。两个项目合计服务器预算不超过 200 元/月；另一个项目暂不调查。DeepSeek 开发验收累计预算 25 元，当前没有真实 API 消耗。

在选定的远程 Linux 主机中复制 `.env.example` 为 `.env`，填写随机 URL-safe 数据库密码、至少 16 字符随机初始密码和实际 HTTPS Origin。不要将密钥写入 Git 或聊天。

```sh
docker compose build
docker compose up -d database
docker compose --profile setup run --rm migrate
docker compose --profile setup run --rm bootstrap
docker compose up -d api worker web
```

已有第一阶段数据库需先备份，再运行迁移到 `0002`。所有命令仅供远程执行。

Web 仅绑定远程主机 `127.0.0.1:8080`，需配置 HTTPS 反向代理。`PUBLIC_ORIGIN` 必须与浏览器 Origin 完全匹配。只在隔离的远程开发环境通过 SSH 隧道使用 HTTP 时设置 `SECURE_COOKIE=false`；正式环境保持 Secure Cookie。

默认 bootstrap 创建分析师；`BOOTSTRAP_ROLE` 允许 `analyst`、`manager`、`admin`。创建额外管理员时使用新的用户名与随机密码，不会覆盖现有账号。管理员角色用于预算查看，不能发起分析。完整用户管理界面尚未实现。

先用规则模式验收：在「数据源」生成样例，创建分析，再输入「只看华东，按渠道」「只看服饰，按品类」「返回全国」「返回上一级」。重开会话会恢复任务记录；刷新浏览器不会重新创建任务。

DeepSeek Key 仅注入 worker。填入已核对的**人民币/百万 token 最高档输入与输出价格**和核对日期，空价格、零价格或超过 7 天的核对日期会阻止调用。账本按最高费率保守估算，不等同于供应商最终账单；超时请求保留预留款待核对。不得删除或重置预算账本来绕过累计预算。详见 [任务与预算说明](docs/data-and-task-contract.md)。

## 本机允许的轻量检查

```sh
cd backend
python -B -m unittest discover -s tests -v
```

这些测试只用标准库，不启动业务服务、不安装依赖。固定预期：GMV 1,000,000 → 648,000；净利润 250,000 → 143,000。

## 文档

- [PRD](docs/经营归因分析系统-PRD.md)
- [已批准技术设计](docs/superpowers/specs/2026-11-21-business-attribution-design.md)
- [实施计划](docs/implementation-plan.md)
- [数据、任务与预算合同](docs/data-and-task-contract.md)
