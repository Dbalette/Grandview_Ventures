import WebKit
import UniformTypeIdentifiers

/// Serves the bundled `www` folder at mirror://app/... .
/// WebKit treats origins served by a scheme handler as secure contexts, so ES modules, fetch,
/// WebAssembly and the camera (getUserMedia) all work exactly as they do on https.
final class LocalSchemeHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "mirror"
    static let host = "app"
    static var indexURL: URL { URL(string: "\(scheme)://\(host)/index.html")! }

    private let root: URL? = Bundle.main.url(forResource: "www", withExtension: nil)

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else { return }
        var path = url.path
        if path.isEmpty || path == "/" { path = "/index.html" }
        let relative = String(path.dropFirst())
        guard let root, !relative.contains(".."), case let fileURL = root.appendingPathComponent(relative),
              let data = try? Data(contentsOf: fileURL) else {
            task.didFailWithError(NSError(domain: NSURLErrorDomain, code: NSURLErrorFileDoesNotExist, userInfo: [NSLocalizedDescriptionKey: "Not in bundle: \(relative)"]))
            return
        }
        let headers: [String: String] = [
            "Content-Type": Self.mimeType(for: fileURL),
            "Content-Length": String(data.count),
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
        ]
        guard let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers) else { return }
        task.didReceive(response)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}

    static func mimeType(for url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "html": return "text/html; charset=utf-8"
        case "js", "mjs": return "text/javascript"
        case "css": return "text/css"
        case "json": return "application/json"
        case "webmanifest": return "application/manifest+json"
        case "wasm": return "application/wasm"
        case "svg": return "image/svg+xml"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "woff2": return "font/woff2"
        case "task", "tflite": return "application/octet-stream"
        default: return UTType(filenameExtension: url.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
        }
    }
}
