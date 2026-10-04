import SwiftUI
import WebKit

/// The whole app is the web page, served from the bundle, with the App Store reached through a message bridge.
struct WebView: UIViewRepresentable {
    let store: StoreManager

    func makeCoordinator() -> Coordinator { Coordinator(store: store) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.setURLSchemeHandler(LocalSchemeHandler(), forURLScheme: LocalSchemeHandler.scheme)
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true

        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "store")
        controller.addUserScript(WKUserScript(source: AppConfig.javascript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        configuration.userContentController = controller

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.uiDelegate = context.coordinator
        webView.navigationDelegate = context.coordinator
        webView.scrollView.bounces = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isOpaque = false
        webView.backgroundColor = UIColor(named: "LaunchBackground")
        webView.allowsBackForwardNavigationGestures = true
        context.coordinator.webView = webView
        store.bridge = context.coordinator
        webView.load(URLRequest(url: LocalSchemeHandler.indexURL))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKScriptMessageHandler, WKUIDelegate, WKNavigationDelegate, StoreBridge {
        let store: StoreManager
        weak var webView: WKWebView?

        init(store: StoreManager) { self.store = store }

        // MARK: JavaScript -> Swift
        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "store", let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            Task { @MainActor in
                switch type {
                case "status":
                    await store.refresh()
                    send(store.statusPayload())
                case "purchase":
                    send(await store.purchase())
                case "restore":
                    send(await store.restore())
                case "manage":
                    await store.manageSubscriptions()
                default:
                    break
                }
            }
        }

        // MARK: Swift -> JavaScript
        @MainActor
        func send(_ payload: [String: Any]) {
            guard let webView,
                  let data = try? JSONSerialization.data(withJSONObject: payload),
                  let json = String(data: data, encoding: .utf8) else { return }
            webView.evaluateJavaScript("window.__mirrorStore && window.__mirrorStore.receive(\(json));", completionHandler: nil)
        }

        // MARK: Camera. The system asks once (NSCameraUsageDescription); WebKit need not ask again.
        func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
            decisionHandler(.grant)
        }

        // MARK: Links. Pages in the bundle stay inside; anything on the web opens in Safari.
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if let url = navigationAction.request.url, let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https" || scheme == "mailto" {
                UIApplication.shared.open(url)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = navigationAction.request.url { UIApplication.shared.open(url) }
            return nil
        }
    }
}
