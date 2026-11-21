# 经营归因分析系统

当前是第一阶段代码，包含可独立校验的指标引擎，以及待远程联调的 FastAPI、PostgreSQL 和 React 工作台。不是已经完成全部 PRD 的生产版本。

## 已编写的能力

- 加法、LMDI、精确 Shapley、比率维度贡献分摊，及两个 PRD 固定样例。
- 两场景条件性模拟、明确的统计证据边界。
- 账号认证、服务端 Cookie、CSRF、业务线授权、个人分析快照、操作审计。
- 三栏工作台、历史会话、贡献瀑布图、数据表、模拟参数、Markdown 数学分解草稿。
- PostgreSQL 初始迁移、远程 Docker Compose 部署配置。

## 当前验证状态

已在本机现有 Python 中运行 10 个无第三方依赖的算法检查，全部通过。本机没有安装项目依赖、启动服务或 Docker。

尚未执行：前端 TypeScript 编译、浏览器验收、FastAPI 接口与真实 PostgreSQL 迁移联调、容器构建。依赖尚无远程生成的锁文件，镜像尚未固定摘要，当前 Compose 用于远程开发集成，不能当作完成生产加固的部署方案。

尚未实现：版本化明细导入、动态指标管理、RLS 与数据库运行账号分离、持久任务队列/SSE、多轮模型探查、统计检验、独立代码沙箱、事件和历史案例检索、历史收益区间、PDF/Excel、报告协作与发布、简报订阅、完整角色管理。详见 [实施计划](docs/implementation-plan.md)。

## 只在远程环境运行

服务器尚未选定。两个项目合计服务器预算不超过 200 元/月；另一个项目暂不调查。DeepSeek 开发验收累计预算 25 元，预计不足时先说明并申请追加；当前代码尚未发起模型调用。

选定远程 Linux 主机后，在远程工作目录复制 `.env.example` 为 `.env`，填写随机 URL-safe 数据库密码、随机初始密码和实际 HTTPS Origin。不要在聊天或 Git 中提交密钥。

```sh
docker compose build
docker compose up -d database
docker compose --profile setup run --rm migrate
docker compose --profile setup run --rm bootstrap
docker compose up -d api web
```

Web 仅绑定远程主机 `127.0.0.1:8080`，需配置 HTTPS 反向代理，且 `PUBLIC_ORIGIN` 必须与浏览器 Origin 完全匹配。不要直接把数据库端口暴露公网。若仅在隔离的远程开发环境通过 SSH 隧道使用 HTTP，须明确设置对应 Origin 和 `SECURE_COOKIE=false`；正式环境保持 Secure Cookie。

初始账号为具有两个样例业务线访问权的分析师。已有账号不会被 bootstrap 覆盖。当前角色管理未实现，不作为完整权限矩阵验收结果。

## 轻量算法检查

以下命令不安装依赖、不创建运行服务，也不写 Python 字节码：

```sh
cd backend
python -B -m unittest discover -s tests -v
```

固定输入的预期值：GMV 1,000,000 → 648,000；净利润 250,000 → 143,000；转化率调整到 3.5% 后 GMV 756,000；原材料下降 5% 后净利润 170,000。

## 文档

- [PRD](docs/经营归因分析系统-PRD.md)
- [已批准技术设计](docs/superpowers/specs/2026-11-21-business-attribution-design.md)
- [实施计划](docs/implementation-plan.md)
