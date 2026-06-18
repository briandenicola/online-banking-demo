module.exports = {
  webpack: {
    configure: (webpackConfig) => {
      // Fix for MUI v9 + react-transition-group webpack 5 fullySpecified issue
      // MUI's .mjs ESM build imports without extensions, webpack 5 requires them
      webpackConfig.module.rules.push({
        test: /\.m?js$/,
        resolve: {
          fullySpecified: false,
        },
      });
      return webpackConfig;
    },
  },
};
