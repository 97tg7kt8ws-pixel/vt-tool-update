# VT小工具独立更新通道

版本清单：`version.json`

软件默认检查地址：

`https://raw.githubusercontent.com/97tg7kt8ws-pixel/vt-tool-update/main/version.json`

## 发布新版本

1. 在仓库的 **Releases** 页面创建新版本，标签和标题使用版本号，例如 `1.8`。
2. 上传新版主程序，文件名使用 `VTTool_1.8.exe`。
3. 发布 Release 后，将 `version.json` 中的 `version`、`url` 和 `note` 更新为对应版本。
4. 旧版本软件启动后会自动检查并提示更新。

请先上传更新程序并发布 Release，再提高 `version.json` 中的版本号，避免用户收到尚未就绪的下载地址。
