"""Convert the disposable Flutter macOS scaffold's test target to XCUITest."""
from pathlib import Path
import argparse
import json
from xml.sax.saxutils import quoteattr

HERE = Path(__file__).resolve().parent


def prepare(app, fixture=None):
    app = Path(app).resolve()
    marker = app / '.herdr-generated-probe.json'
    if not marker.is_file() or json.loads(marker.read_text()).get('kind') != 'herdr-flutter-validation':
        raise ValueError('macos_xcui_scaffold_invalid')
    project = app / 'macos/Runner.xcodeproj/project.pbxproj'
    scheme = app / 'macos/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme'
    source = app / 'macos/RunnerTests/RunnerTests.swift'
    text = project.read_text()
    unit = 'productType = "com.apple.product-type.bundle.unit-test";'
    loader = '\t\t\t\tBUNDLE_LOADER = "$(TEST_HOST)";\n'
    host = '\t\t\t\tTEST_HOST = "$(BUILT_PRODUCTS_DIR)/herdr_flutter_probe.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/herdr_flutter_probe";'
    if text.count(unit) != 1 or text.count(loader) != 3 or text.count(host) != 3 or not source.is_file():
        raise ValueError('macos_xcui_project_unexpected')
    scheme_text = scheme.read_text()
    if scheme_text.count('parallelizable = "YES"') != 1:
        raise ValueError('macos_xcui_scheme_unexpected')
    if fixture is not None:
        fixture = Path(fixture).resolve()
        if not fixture.is_file():
            raise ValueError('macos_xcui_fixture_invalid')
        tag = '\n      <EnvironmentVariables><EnvironmentVariable key="HP_MAC_AX_FIXTURE" value=' + quoteattr(str(fixture)) + ' isEnabled="YES"/></EnvironmentVariables>'
        if scheme_text.count('</Testables>') != 1:
            raise ValueError('macos_xcui_scheme_unexpected')
        scheme_text = scheme_text.replace('</Testables>', '</Testables>' + tag)
    text = text.replace(unit, 'productType = "com.apple.product-type.bundle.ui-testing";')
    text = text.replace(loader, '').replace(host, '\t\t\t\tTEST_TARGET_NAME = Runner;')
    project.write_text(text)
    scheme.write_text(scheme_text.replace('parallelizable = "YES"', 'parallelizable = "NO"'))
    source.write_text((HERE / 'macos_secure_xcuitest.swift').read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--fixture', type=Path)
    args = parser.parse_args()
    prepare(args.app, args.fixture)
