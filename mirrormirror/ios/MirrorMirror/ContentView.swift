import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: StoreManager

    var body: some View {
        ZStack {
            Color("LaunchBackground").ignoresSafeArea()
            WebView(store: store).ignoresSafeArea()
        }
    }
}
