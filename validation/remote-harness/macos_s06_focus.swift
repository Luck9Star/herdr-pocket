import CoreGraphics

enum MacosS06FocusOutline {
    // The focused InputDecorator draws the brand color as a two-point outline.
    // Read both vertical edges away from rounded corners, labels and the caret.
    static func present(in image: CGImage, width: CGFloat, brand: UInt32) -> Bool {
        let columns = image.width
        let rows = image.height
        guard width.isFinite, width >= 24, (24...8192).contains(columns), (16...4096).contains(rows),
              let sRGB = CGColorSpace(name: CGColorSpace.sRGB) else { return false }
        let rowBytes = columns * 4
        var rgba = [UInt8](repeating: 0, count: rowBytes * rows)
        let drawn = rgba.withUnsafeMutableBytes { bytes in
            guard let context = CGContext(data: bytes.baseAddress, width: columns, height: rows,
                bitsPerComponent: 8, bytesPerRow: rowBytes, space: sRGB,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            context.draw(image, in: CGRect(x: 0, y: 0, width: columns, height: rows))
            return true
        }
        guard drawn else { return false }
        let edge = min(columns / 8, Int((6 * CGFloat(columns) / width).rounded(.up)))
        let middle = (3 * rows / 8)..<(5 * rows / 8)
        let red = Int((brand >> 16) & 0xff)
        let green = Int((brand >> 8) & 0xff)
        let blue = Int(brand & 0xff)

        func containsOutline(_ stripe: Range<Int>) -> Bool {
            let hits = middle.filter { row in
                stripe.contains { column in
                    let pixel = row * rowBytes + column * 4
                    return rgba[pixel + 3] >= 240
                        && abs(Int(rgba[pixel]) - red) <= 20
                        && abs(Int(rgba[pixel + 1]) - green) <= 20
                        && abs(Int(rgba[pixel + 2]) - blue) <= 20
                }
            }.count
            return hits * 4 >= middle.count * 3
        }
        return containsOutline(0..<edge) && containsOutline((columns - edge)..<columns)
    }
}
