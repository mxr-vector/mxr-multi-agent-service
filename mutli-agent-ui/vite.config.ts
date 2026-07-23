import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 加载对应环境（.env.[mode]）的变量，读取端口、代理前缀与后端地址
  const env = loadEnv(mode, process.cwd());
  const { VITE_APP_PORT, VITE_APP_BASE_API, VITE_API_BASE_URL } = env;

  return {
    plugins: [
      vue(),
      AutoImport({ resolvers: [ElementPlusResolver()] }),
      Components({ resolvers: [ElementPlusResolver()] }),
    ],
    resolve: {
      alias: {
        // 根路径别名：@ 指向 src 目录
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      host: "0.0.0.0",
      port: Number(VITE_APP_PORT),
      proxy: {
        // 前缀代理：请求 VITE_APP_BASE_API 时转发到后端，并消除前缀
        [VITE_APP_BASE_API]: {
          target: VITE_API_BASE_URL,
          changeOrigin: true,
          rewrite: (path) => path.replace(new RegExp(`^${VITE_APP_BASE_API}`), ""),
        },
      },
    },
    build: {
      // 使用 oxc 进行打包压缩（Vite 8 / Rolldown 内置）
      minify: "oxc",
    },
  };
});
