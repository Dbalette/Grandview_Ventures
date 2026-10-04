import Foundation

/// Values handed to the web page before it runs. Edit the App Store URL once the app has an id.
enum AppConfig {
    static let freeScans = 3
    static let appStoreURL = "https://apps.apple.com/app/mirror-mirror-on-the-wall/id0000000000"

    /// Injected at document start. The page reads window.MM_CONFIG for the free-reading allowance,
    /// the product id, and where to find the bundled vision library and face model.
    static var javascript: String {
        """
        window.MM_CONFIG = {
          platform: 'ios',
          freeScans: \(freeScans),
          productId: '\(StoreManager.productID)',
          price: '$0.99',
          period: 'month',
          appStoreUrl: '\(appStoreURL)',
          visionBases: ['vendor/tasks-vision', 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35'],
          modelUrl: 'vendor/face_landmarker.task'
        };
        """
    }
}
