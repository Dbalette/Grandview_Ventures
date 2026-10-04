import SwiftUI

@main
struct MirrorMirrorApp: App {
    @StateObject private var store = StoreManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
        }
    }
}
