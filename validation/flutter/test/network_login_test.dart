import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/network_login.dart';
import 'package:herdr_flutter_probe/network_runtime.dart';
import 'network_profiles_test.dart' show testNetwork;
import 'network_tailscale_test.dart' show tailscaleBinding;

class PendingLoginRuntime extends NativeNetworkRuntime {
  final calls = <(String,Map<String,Object>)>[];
  final reads = <Completer<Object?>>[],logins = <Completer<Object?>>[];
  @override bool get supported => true;
  @override Future<Object?> call(String method,Map<String,Object> args) {
    calls.add((method,args));
    if (method == 'nodeLoginStatus') { final result = Completer<Object?>(); reads.add(result); return result.future; }
    if (method == 'nodeLogin') { final result = Completer<Object?>(); logins.add(result); return result.future; }
    if (method == 'openLogin') return Future.value({'opened':true});
    throw StateError('unexpected fixture call');
  }
}
Map<String,Object?> loginReply(NetworkNodeBinding binding,String state,{String? url,String? token}) =>
  {'state':state,'binding':binding.toMap(),'authUrl':url,'reviewToken':token};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('initial status is read-only; authorization and browser open are separate explicit actions',() async {
    final runtime = PendingLoginRuntime(),binding = tailscaleBinding(testNetwork());
    final session = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => true,maxPolls:0);
    final refreshing = session.refresh(); expect(runtime.logins,isEmpty);
    runtime.reads.single.complete(loginReply(binding,'needs-login')); await refreshing;
    expect(session.canAuthorize,isTrue); expect(session.canOpen,isFalse);
    final authorizing = session.authorize(); expect(runtime.logins.length,1);
    runtime.logins.single.complete(loginReply(binding,'needs-login',url:'https://login.example.test/one',token:'review-1'));
    await authorizing;
    expect(session.canOpen,isTrue); expect(runtime.calls.where((c) => c.$1 == 'openLogin'),isEmpty);
    await session.authorize(); expect(runtime.logins.length,1);
    await session.open();
    expect(runtime.calls.last.$1,'openLogin');
    expect(runtime.calls.last.$2,{'binding':binding.toMap(),'url':'https://login.example.test/one','reviewToken':'review-1'});
    expect(session.authUrl,isNull); await session.open();
    expect(runtime.calls.where((c) => c.$1 == 'openLogin').length,1); session.dispose();
  });
  test('background and app return discard old status and read only the original binding',() async {
    final runtime = PendingLoginRuntime(),binding = tailscaleBinding(testNetwork());
    final session = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => true,maxPolls:0);
    final old = session.refresh(); session.suspend();
    expect(session.authUrl,isNull); expect(session.canAuthorize,isFalse); expect(session.canOpen,isFalse);
    final resumed = session.resume(); expect(runtime.reads.length,2);
    runtime.reads.last.complete(loginReply(binding,'running')); await resumed;
    runtime.reads.first.complete(loginReply(binding,'needs-login',url:'https://login.example.test/old',token:'review-old')); await old;
    expect(session.state,'running'); expect(session.authUrl,isNull); expect(runtime.logins,isEmpty);
    for (final call in runtime.calls) { expect(call.$2['binding'],binding.toMap()); }
    session.dispose();
  });
  test('authorization completing after hidden review cannot restore its URL or automatically open it',() async {
    final runtime = PendingLoginRuntime(),binding = tailscaleBinding(testNetwork());
    final session = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => true,maxPolls:0);
    final first = session.refresh(); runtime.reads.single.complete(loginReply(binding,'needs-login')); await first;
    final login = session.authorize(); session.suspend();
    runtime.logins.single.complete(loginReply(binding,'needs-login',url:'https://login.example.test/late',token:'review-1')); await login;
    expect(session.authUrl,isNull); expect(session.canOpen,isFalse);
    final resumed = session.resume(); runtime.reads.last.complete(loginReply(binding,'needs-machine-auth')); await resumed;
    expect(session.state,'needs-machine-auth'); expect(runtime.logins.length,1);
    expect(runtime.calls.where((c) => c.$1 == 'openLogin'),isEmpty); session.dispose();
  });
  test('unknown authorization is read back without replay even when state still needs login',() async {
    final runtime = PendingLoginRuntime(),binding = tailscaleBinding(testNetwork());
    final session = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => true,maxPolls:0);
    final first = session.refresh(); runtime.reads.single.complete(loginReply(binding,'needs-login')); await first;
    final login = session.authorize(); runtime.logins.single.completeError(StateError('unknown')); await login;
    expect(session.known,isFalse); expect(session.notice,contains('未确认'));
    final refresh = session.refresh(); runtime.reads.last.complete(loginReply(binding,'needs-login')); await refresh;
    expect(session.canAuthorize,isFalse); await session.authorize(); expect(runtime.logins.length,1); session.dispose();
  });
  test('a fresh review of the same URL replaces its token before explicit browser open',() async {
    final runtime = PendingLoginRuntime(),binding = tailscaleBinding(testNetwork());
    final session = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => true,maxPolls:0);
    final first = session.refresh();
    runtime.reads.single.complete(loginReply(binding,'needs-login',url:'https://login.example.test/same',token:'review-old')); await first;
    final second = session.refresh(); expect(session.canOpen,isFalse); expect(session.authUrl,isNull);
    runtime.reads.last.complete(loginReply(binding,'needs-login',url:'https://login.example.test/same',token:'review-new')); await second;
    await session.open(); expect(runtime.calls.last.$2['reviewToken'],'review-new');
    expect(runtime.logins,isEmpty); session.dispose();
  });
  test('catalog review becoming stale clears paired URL/token and rejects late login and open',() async {
    final runtime = PendingLoginRuntime(),binding = tailscaleBinding(testNetwork()); var current = true;
    final session = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => current,maxPolls:0);
    final first = session.refresh(); runtime.reads.single.complete(loginReply(binding,'needs-login')); await first;
    final login = session.authorize(); current = false; session.checkCurrent();
    runtime.logins.single.complete(loginReply(binding,'needs-login',url:'https://login.example.test/stale',token:'review-1')); await login;
    await session.open(); await session.refresh();
    expect(session.authUrl,isNull); expect(session.canOpen,isFalse); expect(runtime.reads.length,1);
    expect(runtime.calls.where((c) => c.$1 == 'openLogin'),isEmpty); session.dispose();
  });
  testWidgets('automatic polling has a hard read budget and never invokes login or browser',(tester) async {
    final runtime = PendingLoginRuntime(),binding = tailscaleBinding(testNetwork());
    final session = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => true,maxPolls:2);
    final first = session.refresh(); runtime.reads.single.complete(loginReply(binding,'needs-machine-auth')); await first;
    for (var i=0;i<2;i++) {
      await tester.pump(const Duration(seconds:2));
      expect(runtime.reads.length,i+2); runtime.reads.last.complete(loginReply(binding,'needs-machine-auth')); await tester.pump();
    }
    await tester.pump(const Duration(seconds:20));
    expect(runtime.reads.length,3); expect(runtime.logins,isEmpty); expect(session.notice,contains('已暂停'));
    session.dispose();
  });
  test('closing and reopening reads surviving node without repeating pending authorization',() async {
    final runtime = PendingLoginRuntime(),binding = tailscaleBinding(testNetwork());
    final first = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => true,maxPolls:0);
    final reading = first.refresh(); runtime.reads.single.complete(loginReply(binding,'needs-login')); await reading;
    final login = first.authorize(); first.dispose();
    final reopened = NetworkLoginSession(binding:binding,runtime:runtime,stillCurrent:() => true,maxPolls:0);
    final latest = reopened.refresh(); runtime.reads.last.complete(loginReply(binding,'running')); await latest;
    runtime.logins.single.complete(loginReply(binding,'needs-login',url:'https://login.example.test/old',token:'review-1')); await login;
    expect(reopened.state,'running'); expect(reopened.authUrl,isNull); expect(runtime.logins.length,1);
    reopened.dispose();
  });
}
