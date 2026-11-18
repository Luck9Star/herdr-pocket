import Foundation

enum PocketWebViewInsets {
    // UIKit geometry is in points. Return only the part of the top safe area
    // that the WebView frame and its UIKit scroll inset have not consumed.
    static func topOverlapPixels(safeTop: CGFloat, webViewTop: CGFloat, contentInset: CGFloat, scale: CGFloat) -> Double? {
        let overlap = max(0, safeTop - webViewTop - contentInset) * scale
        guard safeTop.isFinite, webViewTop.isFinite, contentInset.isFinite, scale > 0, overlap.isFinite else { return nil }
        return Double(overlap)
    }
}
