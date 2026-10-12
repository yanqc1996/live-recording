# Desktop UI

播录助手桌面界面使用 React、TypeScript、Vite 和 Mantine。业务代码按页面拆分：

- `src/api.ts`：本地 HTTP API 客户端与统一错误处理。
- `src/types.ts`：跨页面共享的数据类型和 Electron bridge 类型。
- `src/components.tsx`：面板、状态、布局和格式化组件。
- `src/pages/`：工作台、主播库、直播监听、作品拉取、媒体归档和设置。
- `src/App.tsx`：应用外壳、导航、全局状态轮询和顶部快捷控制。

开发时运行 `npm run ui:dev`，发布前运行 `npm run ui:build`。桌面打包脚本会自动执行 UI 构建，并将单文件产物放入 Python 运行时。
