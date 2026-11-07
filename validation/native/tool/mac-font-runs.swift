// Run from the repository root with the macOS command-line tools.
// Loads the same font bytes as both GUIs, without registering or installing it.
import Foundation
import CoreGraphics
import CoreText

struct Sample: Decodable { let id: String, text: String }
struct Fixture: Decodable { let samples: [Sample] }
struct FontRun: Encodable { let font: String, glyphCount: Int, missingGlyphs: Int }
struct SampleRuns: Encodable { let id: String, runs: [FontRun] }

let assets = URL(fileURLWithPath: "validation/shared", isDirectory: true)
let fixture = try JSONDecoder().decode(Fixture.self, from:
    Data(contentsOf: assets.appendingPathComponent("terminal-font-diagnostics-v1.json")))
let fontURL = assets.appendingPathComponent("fonts/JetBrainsMonoNerdFontMono-Regular.ttf")
guard let provider = CGDataProvider(url: fontURL as CFURL), let graphicsFont = CGFont(provider) else {
    throw CocoaError(.fileReadCorruptFile)
}
let configured = CTFontCreateWithGraphicsFont(graphicsFont, 14, nil, nil)
let key = NSAttributedString.Key(kCTFontAttributeName as String)
let records = fixture.samples.map { sample -> SampleRuns in
    let text = NSAttributedString(string: sample.text, attributes: [key: configured])
    let line = CTLineCreateWithAttributedString(text)
    let runs = (CTLineGetGlyphRuns(line) as! [CTRun]).map { run -> FontRun in
        let attributes = CTRunGetAttributes(run) as NSDictionary
        let font = attributes[kCTFontAttributeName] as! CTFont
        let count = CTRunGetGlyphCount(run)
        var glyphs = [CGGlyph](repeating: 0, count: count)
        if count > 0 { CTRunGetGlyphs(run, CFRange(location: 0, length: count), &glyphs) }
        return FontRun(font: CTFontCopyPostScriptName(font) as String, glyphCount: count,
                       missingGlyphs: glyphs.filter { $0 == 0 }.count)
    }
    return SampleRuns(id: sample.id, runs: runs)
}
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
print(String(decoding: try encoder.encode(records), as: UTF8.self))
