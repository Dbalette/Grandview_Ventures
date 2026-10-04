import Foundation
import StoreKit
import UIKit

/// Something that can deliver a message to the web page.
@MainActor
protocol StoreBridge: AnyObject {
    func send(_ payload: [String: Any])
}

/// StoreKit 2: one auto-renewing subscription, Mirror Mirror Premium, US$0.99 a month.
@MainActor
final class StoreManager: ObservableObject {
    static let productID = "com.grandviewventures.mirrormirror.monthly"

    @Published private(set) var product: Product?
    @Published private(set) var isEntitled = false
    @Published private(set) var expirationDate: Date?
    weak var bridge: StoreBridge?

    private var updatesTask: Task<Void, Never>?

    init() {
        updatesTask = Task { [weak self] in
            for await result in Transaction.updates {
                guard let self else { continue }
                if case .verified(let transaction) = result { await transaction.finish() }
                await self.refresh()
                self.bridge?.send(self.statusPayload())
            }
        }
        Task { await refresh() }
    }

    deinit { updatesTask?.cancel() }

    /// Load the product (once) and re-read the current entitlement from StoreKit.
    func refresh() async {
        if product == nil {
            product = try? await Product.products(for: [Self.productID]).first
        }
        var entitled = false
        var expires: Date? = nil
        for await result in Transaction.currentEntitlements {
            if case .verified(let transaction) = result, transaction.productID == Self.productID, transaction.revocationDate == nil {
                entitled = true
                expires = transaction.expirationDate
            }
        }
        isEntitled = entitled
        expirationDate = expires
    }

    func statusPayload() -> [String: Any] {
        var payload: [String: Any] = ["type": "status", "entitled": isEntitled, "productId": Self.productID]
        if let product {
            payload["price"] = product.displayPrice
            payload["period"] = Self.periodText(product)
        }
        if let expirationDate {
            payload["expires"] = ISO8601DateFormatter().string(from: expirationDate)
        }
        return payload
    }

    func purchase() async -> [String: Any] {
        if product == nil { await refresh() }
        guard let product else {
            return ["type": "purchase", "ok": false, "entitled": isEntitled, "error": "The subscription is not available right now. Please try again in a moment."]
        }
        do {
            let result = try await product.purchase()
            switch result {
            case .success(let verification):
                if case .verified(let transaction) = verification { await transaction.finish() }
                await refresh()
                return ["type": "purchase", "ok": isEntitled, "entitled": isEntitled]
            case .userCancelled:
                return ["type": "purchase", "ok": false, "cancelled": true, "entitled": isEntitled]
            case .pending:
                return ["type": "purchase", "ok": false, "pending": true, "entitled": isEntitled]
            @unknown default:
                return ["type": "purchase", "ok": false, "entitled": isEntitled]
            }
        } catch {
            return ["type": "purchase", "ok": false, "entitled": isEntitled, "error": error.localizedDescription]
        }
    }

    func restore() async -> [String: Any] {
        do { try await AppStore.sync() } catch { /* the user may have dismissed the sign-in; the entitlement check below still runs */ }
        await refresh()
        return ["type": "restore", "ok": true, "entitled": isEntitled]
    }

    func manageSubscriptions() async {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        guard let scene = scenes.first(where: { $0.activationState == .foregroundActive }) ?? scenes.first else { return }
        try? await AppStore.showManageSubscriptions(in: scene)
    }

    static func periodText(_ product: Product) -> String {
        guard let period = product.subscription?.subscriptionPeriod else { return "month" }
        let n = period.value
        switch period.unit {
        case .day: return n == 7 ? "week" : (n == 1 ? "day" : "\(n) days")
        case .week: return n == 1 ? "week" : "\(n) weeks"
        case .month: return n == 1 ? "month" : "\(n) months"
        case .year: return n == 1 ? "year" : "\(n) years"
        @unknown default: return "month"
        }
    }
}
