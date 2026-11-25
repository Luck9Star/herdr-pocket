import CoreGraphics

enum MacosS06FocusOutline {
    private struct BrandPixels {
        let columns: Int
        let rows: Int
        let rgba: [UInt8]
        let red: Int
        let green: Int
        let blue: Int

        init?(image: CGImage, brand: UInt32) {
            columns = image.width
            rows = image.height
            guard (24...8192).contains(columns), (16...4096).contains(rows),
                  let sRGB = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
            let width = columns, height = rows
            let rowBytes = width * 4
            var pixels = [UInt8](repeating: 0, count: rowBytes * height)
            let drawn = pixels.withUnsafeMutableBytes { bytes in
                guard let context = CGContext(data: bytes.baseAddress, width: width, height: height,
                    bitsPerComponent: 8, bytesPerRow: rowBytes, space: sRGB,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
                context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
                return true
            }
            guard drawn else { return nil }
            rgba = pixels
            red = Int((brand >> 16) & 0xff)
            green = Int((brand >> 8) & 0xff)
            blue = Int(brand & 0xff)
        }

        func matches(column: Int, row: Int) -> Bool {
            let pixel = (row * columns + column) * 4
            return rgba[pixel + 3] >= 240
                && abs(Int(rgba[pixel]) - red) <= 20
                && abs(Int(rgba[pixel + 1]) - green) <= 20
                && abs(Int(rgba[pixel + 2]) - blue) <= 20
        }

        var middle: Range<Int> { (3 * rows / 8)..<(5 * rows / 8) }
    }

    // Inspect the focused editor outline away from rounded corners, labels and the caret.
    static func present(in image: CGImage, width: CGFloat, brand: UInt32) -> Bool {
        guard width.isFinite, width >= 24, let pixels = BrandPixels(image: image, brand: brand) else { return false }
        let columns = pixels.columns
        let edge = min(columns / 8, Int((6 * CGFloat(columns) / width).rounded(.up)))
        func containsOutline(_ stripe: Range<Int>) -> Bool {
            let hits = pixels.middle.filter { row in
                stripe.contains { column in pixels.matches(column: column, row: row) }
            }.count
            return hits * 4 >= pixels.middle.count * 3
        }
        return containsOutline(0..<edge) && containsOutline((columns - edge)..<columns)
    }

    // The FilledButton uses the theme's primary fill when enabled. Inspect
    // two interior patches outside the centered label and rounded edges.
    static func filledButton(in image: CGImage, brand: UInt32) -> Bool? {
        guard let pixels = BrandPixels(image: image, brand: brand) else { return nil }
        let width = pixels.columns
        let patches = [(width / 8)..<(width / 4), (3 * width / 4)..<(7 * width / 8)]
        return patches.allSatisfy { patch in
            let hits = pixels.middle.reduce(0) { total, row in
                total + patch.filter { pixels.matches(column: $0, row: row) }.count
            }
            return hits * 10 >= patch.count * pixels.middle.count * 9
        }
    }
}
