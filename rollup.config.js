import deckyPlugin from "@decky/rollup";
import replace from "@rollup/plugin-replace";
import { readFileSync } from "fs";

const { version } = JSON.parse(readFileSync("./package.json", "utf-8"));

// @decky/rollup's deckyPlugin() merges (concats) our plugins with its defaults.
// The default config only replaces process.env.NODE_ENV, so re-add the
// __PLUGIN_VERSION__ substitution the old build performed (used in About.tsx).
export default deckyPlugin({
  plugins: [
    replace({
      preventAssignment: true,
      __PLUGIN_VERSION__: JSON.stringify(version),
    }),
  ],
});
