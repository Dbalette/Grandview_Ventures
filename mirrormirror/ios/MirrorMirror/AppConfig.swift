import Foundation

/// Values handed to the web page before it runs. Edit the App Store URL once the app has an id.
enum AppConfig {
    static let productID = "com.grandviewventures.mirrormirror.monthly"
    static let freeScans = 3
    static let appStoreURL = "https://apps.apple.com/app/mirror-mirror-on-the-wall/id0000000000"

    /// Injected at document start. The page reads window.MM_CONFIG for the free-reading allowance,
    /// the product id, and where to find the bundled vision library and face model.
    static var javascript: String {
        var script = """
        window.MM_CONFIG = {
          platform: 'ios',
          freeScans: \(freeScans),
          productId: '\(productID)',
          price: '$0.99',
          period: 'month',
          appStoreUrl: '\(appStoreURL)',
          visionBases: ['vendor/tasks-vision', 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35'],
          modelUrl: 'vendor/face_landmarker.task'
        };
        """
        #if DEBUG
        script += "\n" + debugConsoleBridge
        #endif
        return script
    }

    #if DEBUG
    /// Debug builds forward the page's console and errors to the native log, so a run on a simulator or a
    /// device can be read without Safari's Web Inspector. Release builds contain none of this.
    private static let debugConsoleBridge = """
    (function () {
      var describe = function (a) {
        if (typeof a === 'string') return a;
        if (a instanceof Error) return a.name + ': ' + a.message;
        try { return JSON.stringify(a); } catch (e) { return String(a); }
      };
      var post = function (level, args) {
        try { window.webkit.messageHandlers.log.postMessage({ level: level, text: Array.prototype.map.call(args, describe).join(' ') }); } catch (e) {}
      };
      ['log', 'info', 'warn', 'error'].forEach(function (level) {
        var original = console[level];
        console[level] = function () { post(level, arguments); return original.apply(console, arguments); };
      });
      window.addEventListener('error', function (e) { post('error', ['window.onerror', e.message, e.filename, e.lineno]); });
      window.addEventListener('unhandledrejection', function (e) { post('error', ['unhandledrejection', describe(e.reason)]); });
    })();
    """
    #endif
}
