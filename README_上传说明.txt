A股资金流向看板修复上传包

文件结构必须保持：
- index.html（仓库根目录）
- data/dashboard.json
- scripts/update_data.py
- .github/workflows/update-data.yml

上传方法：
1. 在 GitHub 仓库根目录使用 Add file -> Upload files。
2. 上传本压缩包解压后的所有文件，保留目录结构；如果网页端不方便上传以点开头的 .github 目录，请在仓库中单独创建 .github/workflows/update-data.yml，或用电脑上传整个目录。
3. 确认同名 index.html 替换旧文件，Commit changes。
4. 进入仓库 Actions，选择 “Update A-share dashboard data”，点击 Run workflow，运行一次。
5. 检查 Actions 运行成功后，打开 data/dashboard.json 确认 data_date 和行业/概念数组有真实数据，再打开 GitHub Pages 网站。
6. 后续 GitHub Actions 会在工作日北京时间盘中定时运行，并尝试保存最新有效数据。非交易日不会定时刷新（节假日仍可能有一次工作日计划触发，接口失败时脚本尽量保留旧数据）。

重要说明：
- 此包不包含虚构行情；初始 dashboard.json 是空的，第一次 Actions 成功拉取真实数据后才会有数据。
- GitHub Actions 定时任务可能延迟，且 AkShare/东方财富公开接口可能限流或改变字段。运行失败时请打开 Actions 查看日志。
- 资金流向属于平台估算口径，不等于交易所官方机构资金账本。
- index.html 优先读取云端 data/dashboard.json；若没有有效板块数据，会尝试浏览器端公开接口。
