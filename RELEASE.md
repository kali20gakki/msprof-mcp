# Release Guide

本文档说明 `msprof-mcp` 的发版流程，包括：

- 修改版本号
- 创建并推送 Git tag
- 通过 GitHub Actions 自动构建多平台 wheel
- 自动发布 GitHub Release
- 可选自动发布到 PyPI

当前相关 workflow：

- [`.github/workflows/build-wheels.yml`](./.github/workflows/build-wheels.yml)
- [`.github/workflows/publish-release.yml`](./.github/workflows/publish-release.yml)

## 1. 前置条件

### GitHub Release

默认已启用，无需额外配置。只要推送符合规则的 tag，workflow 就会自动创建或更新 GitHub Release，并上传构建产物。

### PyPI 发布

PyPI 发布是可选的，默认关闭。

当前仓库使用的是 **PyPI Trusted Publisher + GitHub OIDC**，**不需要**手动创建或保存 `PYPI_TOKEN`。也就是说：

- 不需要在 GitHub Secrets 中添加 `PYPI_API_TOKEN`
- 不需要在 workflow 中写用户名/密码
- 只需要在 GitHub 和 PyPI 两边各做一次信任配置

要启用它，需要完成以下配置：

1. 在 GitHub 仓库 `Settings > Secrets and variables > Actions > Variables` 中添加仓库变量：

```text
PUBLISH_TO_PYPI=true
```

2. 在 GitHub 仓库 `Settings > Environments` 中创建环境：

```text
Name: pypi
```

3. 在 PyPI 项目中配置 Trusted Publisher，使当前 GitHub 仓库的 `publish-release.yml` 可以通过 OIDC 发布。

具体操作如下：

1. 登录 PyPI。
2. 打开项目 `msprof-mcp` 的管理页面。
3. 进入 `Manage > Publishing`。
4. 点击 `Add a publisher`。
5. 选择 `GitHub Actions`。
6. 按下面的值填写：

```text
PyPI project name: msprof-mcp
Owner: kali20gakki
Repository name: msprof-mcp
Workflow name: publish-release.yml
Environment name: pypi
```

7. 保存配置。

配置完成后，PyPI 会信任这个 GitHub 仓库中的这个 workflow；当 workflow 运行到发布步骤时，GitHub Actions 会通过 OIDC 自动向 PyPI 申请短期凭证并完成上传。

如果你在 PyPI 页面里看到的是 `Repository owner` / `Repository name` / `Workflow filename` 之类的字段名，含义是一样的，按上面的值填写即可。

如果 `msprof-mcp` 这个项目还没有在 PyPI 上创建：

- 需要先在 PyPI 中创建对应项目，或者
- 使用 PyPI 的 pending publisher 流程预先登记发布者

当前本仓库文档默认按“PyPI 上已经存在 `msprof-mcp` 项目”来说明。

如果没有完成上面的配置，tag 发布时仍然会正常创建 GitHub Release，只是不会上传到 PyPI。

## 2. 修改版本号

发版前先修改 [`pyproject.toml`](./pyproject.toml) 中的版本号：

```toml
[project]
version = "0.1.2"
```

版本号与 tag 必须严格一致。也就是说：

- `pyproject.toml` 里是 `0.1.2`
- Git tag 必须是 `v0.1.2`

如果不一致，发布 workflow 会在 `validate-tag` 阶段直接失败。

## 3. 本地自检

建议在打 tag 前至少做一次本地检查：

```bash
python scripts/download_trace_processor_shell.py --all --clean
uv build
```

可选检查项：

- 确认 `dist/` 下生成了 `.whl` 和 `.tar.gz`
- 确认版本号正确
- 确认本地改动已经提交

## 4. 提交代码

将版本号修改和其它发版相关改动提交到目标分支：

```bash
git add pyproject.toml
git commit -m "release: bump version to 0.1.2"
git push origin main
```

如果你的默认分支不是 `main`，请替换成实际分支名。

## 5. 创建并推送 Tag

创建与版本号一致的 tag：

```bash
git tag v0.1.2
git push origin v0.1.2
```

如果版本已经提交但 tag 尚未创建，不会触发自动发布。

## 6. 自动发布流程

推送 `v*` tag 后，[`.github/workflows/publish-release.yml`](./.github/workflows/publish-release.yml) 会自动执行以下步骤：

1. 校验 tag 与 [`pyproject.toml`](./pyproject.toml) 里的版本是否一致。
2. 调用 [`.github/workflows/build-wheels.yml`](./.github/workflows/build-wheels.yml) 构建多平台 wheel。
3. 构建 source distribution (`sdist`)。
4. 创建或更新 GitHub Release，并上传所有构建产物。
5. 如果设置了 `PUBLISH_TO_PYPI=true`，再将 wheel 和 sdist 发布到 PyPI。

当前 wheel 构建目标平台为：

- Linux `x86_64`
- Linux `arm64`
- Windows `amd64`
- macOS `x86_64`
- macOS `arm64`

## 7. 手动触发 Wheel 构建

如果你只想先验证构建，不想立即发版，可以手动运行 [`.github/workflows/build-wheels.yml`](./.github/workflows/build-wheels.yml)：

1. 打开 GitHub 仓库的 `Actions`
2. 选择 `Build Wheels`
3. 点击 `Run workflow`

这个 workflow 只会构建并上传 artifact，不会创建 Release，也不会发布到 PyPI。

## 8. 发布成功后的结果

成功后你会看到：

- GitHub Releases 页面出现对应的 release，例如 `v0.1.2`
- Release 附件中包含多平台 `.whl`
- Release 附件中包含一个 `.tar.gz` 源码包
- 如果启用了 PyPI 发布，PyPI 上会出现对应版本
- GitHub Actions 运行详情的 `Summary` 中会显示可点击的 artifact 下载链接，以及 GitHub Release / PyPI 链接

## 9. 常见问题

### Tag 和版本号不一致

现象：`validate-tag` 失败。

处理方式：

1. 检查 [`pyproject.toml`](./pyproject.toml) 中的 `version`
2. 检查推送的 tag 是否为 `v{version}`
3. 修正后重新打 tag

### GitHub Release 成功，但 PyPI 没有发布

常见原因：

- 没有设置 `PUBLISH_TO_PYPI=true`
- 没有创建 `pypi` environment
- PyPI Trusted Publisher 没有配置好
- PyPI 中填写的 `owner`、`repository`、`workflow filename` 或 `environment name` 与实际不一致
- 该版本已经存在于 PyPI，PyPI 不允许覆盖上传

### 是否需要配置 PyPI Token

不需要。

当前仓库的发布方式是：

- GitHub Actions workflow: `.github/workflows/publish-release.yml`
- 发布 job: `publish-pypi`
- 认证方式: GitHub OIDC + PyPI Trusted Publisher

只要 GitHub 仓库变量、`pypi` environment、以及 PyPI Trusted Publisher 三者配置正确，推送版本 tag 时就会自动发布到 PyPI。

### 某个平台 wheel 构建失败

常见原因：

- 对应 GitHub runner 不可用
- 平台 runner 发生临时故障
- 下载 `trace_processor_shell` 失败

处理方式：

- 先重试 workflow
- 如果是 runner 标签不可用，调整 [`.github/workflows/build-wheels.yml`](./.github/workflows/build-wheels.yml) 中的矩阵配置
- 必要时改成 self-hosted runner

## 10. 推荐发版命令示例

假设当前要发布 `0.1.2`：

```bash
# 1. 修改 pyproject.toml 中的 version = "0.1.2"

# 2. 本地检查
python scripts/download_trace_processor_shell.py --all --clean
uv build

# 3. 提交版本修改
git add pyproject.toml
git commit -m "release: bump version to 0.1.2"
git push origin main

# 4. 打 tag 并推送
git tag v0.1.2
git push origin v0.1.2
```

完成后等待 GitHub Actions 跑完即可。
