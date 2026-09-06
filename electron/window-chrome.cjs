"use strict";

// The traffic lights are 12pt tall. Keep their center on the toolbar centerline.
// The shared-constants contract also checks the renderer and embedded browser.
const WINDOW_CHROME_HEIGHT = 56;
const TRAFFIC_LIGHT_POSITION = { x: 14, y: (WINDOW_CHROME_HEIGHT - 12) / 2 };
module.exports = { WINDOW_CHROME_HEIGHT, TRAFFIC_LIGHT_POSITION };
