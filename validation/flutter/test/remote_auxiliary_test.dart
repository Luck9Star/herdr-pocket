import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/remote_auxiliary.dart';

void main() {
  test('ASCII and cursor combinations match the shared terminal encoding', () {
    for (final key in 'abcdefghijklmnopqrstuvwxyz'.split('')) {
      final control = String.fromCharCode(key.codeUnitAt(0)-96);
      expect(auxiliaryKey(key,ctrl:true),control);
      expect(auxiliaryKey(key,alt:true),'\x1b$key');
      expect(auxiliaryKey(key,ctrl:true,alt:true),'\x1b$control');
    }
    expect(auxiliaryKey('space',ctrl:true),'\x00');
    expect(auxiliaryKey('up'),'\x1b[A');
    expect(auxiliaryKey('up',applicationCursorMode:true),'\x1bOA');
    for (final app in [false,true]) {
      expect(auxiliaryKey('up',applicationCursorMode:app,ctrl:true),'\x1b[1;5A');
      expect(auxiliaryKey('left',applicationCursorMode:app,alt:true),'\x1b[1;3D');
      expect(auxiliaryKey('down',applicationCursorMode:app,ctrl:true,alt:true),'\x1b[1;7B');
      expect(auxiliaryKey('home',applicationCursorMode:app,alt:true),'\x1b[1;3H');
      expect(auxiliaryKey('pgdn',applicationCursorMode:app,ctrl:true),'\x1b[6;5~');
      expect(auxiliaryKey('ctrl-c',applicationCursorMode:app,ctrl:true,alt:true),'\x03');
    }
    expect(auxiliaryKey('enter'),'\r');
    expect(auxiliaryKey('tab',ctrl:true),isNull);
    expect(auxiliaryKey('中文',alt:true),isNull);
  });
  test('hold, toggle, cancel, invalid lease and base selection release without retries', () {
    final keys = AuxiliaryModifiers();
    keys.toggle('ctrl',allowed:true); keys.toggle('alt',allowed:true);
    expect(keys.ctrl,isTrue); expect(keys.alt,isTrue);
    expect(keys.take('c',applicationCursorMode:false,allowed:true),'\x1b\x03');
    expect(keys.held,isFalse);
    expect(keys.take('c',applicationCursorMode:false,allowed:true),'c');
    keys.toggle('ctrl',allowed:true); keys.toggle('ctrl',allowed:true); expect(keys.held,isFalse);
    keys.toggle('alt',allowed:true); keys.reset(); expect(keys.held,isFalse);
    keys.toggle('ctrl',allowed:true);
    expect(keys.take('c',applicationCursorMode:false,allowed:false),isNull); expect(keys.held,isFalse);
    expect(keys.toggle('alt',allowed:false),isFalse);
    keys.toggle('ctrl',allowed:true);
    expect(keys.take('tab',applicationCursorMode:false,allowed:true),isNull); expect(keys.held,isFalse);
  });
}
