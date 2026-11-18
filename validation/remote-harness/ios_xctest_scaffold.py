"""Prepare the generated, isolated Flutter project for native XCTest only."""
from pathlib import Path

RUNNER_TEST = '@import XCTest;\n@import integration_test;\n\nINTEGRATION_TEST_IOS_RUNNER(RunnerTests)\n'
PODFILE = '''platform :ios, '15.0'
ENV['COCOAPODS_DISABLE_STATS'] = 'true'
project 'Runner', { 'Debug' => :debug, 'Profile' => :release, 'Release' => :release }
def flutter_root
  path = File.expand_path(File.join('..', 'Flutter', 'Generated.xcconfig'), __FILE__)
  File.foreach(path) do |line|
    match = line.match(/FLUTTER_ROOT\\=(.*)/)
    return match[1].strip if match
  end
  raise 'FLUTTER_ROOT missing'
end
require File.expand_path(File.join('packages', 'flutter_tools', 'bin', 'podhelper'), flutter_root)
flutter_ios_podfile_setup
target 'Runner' do
  use_frameworks!
  flutter_install_all_ios_pods File.dirname(File.realpath(__FILE__))
  target 'RunnerTests' do
    inherit! :search_paths
  end
end
post_install do |installer|
  installer.pods_project.targets.each do |target|
    flutter_additional_ios_build_settings(target)
  end
end
'''


def prepare(app):
    app = Path(app)
    project = app / 'ios/Runner.xcodeproj/project.pbxproj'
    swift = app / 'ios/RunnerTests/RunnerTests.swift'
    objc = app / 'ios/RunnerTests/RunnerTests.m'
    podfile = app / 'ios/Podfile'
    debug = app / 'ios/Flutter/Debug.xcconfig'
    scheme = app / 'ios/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme'
    if not swift.is_file() or objc.exists() or podfile.is_symlink():
        raise ValueError('ios_xctest_scaffold_unexpected')
    if podfile.exists():
        existing = podfile.read_text()
        if not all(part in existing for part in ("target 'Runner' do", "target 'RunnerTests' do",
                                                 'inherit! :search_paths', 'flutter_install_all_ios_pods')):
            raise ValueError('ios_xctest_podfile_unexpected')
    text = project.read_text()
    old = 'lastKnownFileType = sourcecode.swift; path = RunnerTests.swift;'
    if text.count('RunnerTests.swift') != 6 or text.count(old) != 1:
        raise ValueError('ios_xctest_project_unexpected')
    text = text.replace(old, 'lastKnownFileType = sourcecode.c.objc; path = RunnerTests.m;')
    text = text.replace('RunnerTests.swift', 'RunnerTests.m')
    config = debug.read_text()
    scheme_text = scheme.read_text()
    if scheme_text.count('parallelizable = "YES"') != 1:
        raise ValueError('ios_xctest_scheme_unexpected')
    pods_line = '#include? "Pods/Target Support Files/Pods-Runner/Pods-Runner.debug.xcconfig"\n'
    if config not in ('#include "Generated.xcconfig"\n', pods_line + '#include "Generated.xcconfig"\n'):
        raise ValueError('ios_xctest_config_unexpected')
    objc.write_text(RUNNER_TEST)
    swift.unlink()
    project.write_text(text)
    scheme.write_text(scheme_text.replace('parallelizable = "YES"', 'parallelizable = "NO"'))
    if not config.startswith(pods_line):
        debug.write_text(pods_line + config)
    if not podfile.exists():
        podfile.write_text(PODFILE)
