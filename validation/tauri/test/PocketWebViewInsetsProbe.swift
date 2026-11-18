import Foundation

@main struct PocketWebViewInsetsProbe {
    static func main() {
        let overlap = PocketWebViewInsets.topOverlapPixels
        precondition(overlap(47, 0, 0, 3) == 141)   // Edge-to-edge portrait.
        precondition(overlap(24, 0, 0, 2) == 48)
        precondition(overlap(47, 20, 12, 3) == 45)  // Frame and UIKit consumed part of the inset.
        precondition(overlap(54, 54, 0, 3) == 0)   // WebView already begins in the safe area.
        precondition(overlap(54, 0, 54, 3) == 0)   // UIKit already insets scroll content.
        precondition(overlap(0, 0, 0, 3) == 0)     // Legitimate landscape zero.
        precondition(overlap(0, 0, 0, 2) == 0)     // Legitimate zero at either scale.
        precondition(overlap(47, 0, -2.5, 3) == 148.5)
        precondition(overlap(47, .nan, 0, 3) == nil)
        precondition(overlap(47, 0, 0, 0) == nil)
    }
}
