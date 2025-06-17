import { resolve } from 'path';

import { defineConfig } from 'vite';
import istanbul from 'vite-plugin-istanbul';
import { compileClient } from 'pug';
import inject from '@rollup/plugin-inject';

function pugPlugin() {
  return {
    name: 'pug',
    transform(src: string, id: string) {
      if (id.endsWith('.pug')) {
        return {
          code: `${compileClient(src, {filename: id})}\nexport default template`,
          map: null,
        };
      }
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    pugPlugin(),
    istanbul({
      include: 'src/*',
      exclude: ['node_modules', 'test/'],
      extension: [ '.js', '.ts', '.vue' ],
      // requireEnv: true,
    }),
    inject({
      $: 'jquery',
      jQuery: 'jquery',
      'window.jQuery': 'jquery'
    }),
  ],
  build: {
    sourcemap: true,
    lib: {
      entry: resolve(__dirname, 'main.js'),
      name: 'GirderPluginJSONForms',
      fileName: 'girder-plugin-jsonforms',
    },
  },
});
