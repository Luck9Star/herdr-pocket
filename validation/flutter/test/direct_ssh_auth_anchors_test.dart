import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:herdr_flutter_probe/design_tokens.dart';
import 'package:herdr_flutter_probe/direct_ssh_page.dart';
import 'package:herdr_flutter_probe/host_catalog.dart';
import 'package:herdr_flutter_probe/host_catalog_page.dart';

import 'direct_ssh_host_key_change_widget_test.dart' show RotationPeer;
import 'direct_ssh_widget_test.dart' show waitFor;
import 'host_catalog_test.dart' show MemoryCatalogStorage;

Future<void>? anchorFonts;

Future<void> loadAnchorFonts(String root) async {
  for (final (family, names) in [
    (
      'AnchorSanFrancisco',
      ['SFNS-400.ttf', 'SFNS-500.ttf', 'SFNS-600.ttf', 'SFNS-700.ttf'],
    ),
    (
      'AnchorPingFang',
      ['PingFangSC-400.otf', 'PingFangSC-500.otf', 'PingFangSC-600.otf'],
    ),
  ]) {
    final loader = FontLoader(family);
    for (final name in names) {
      loader.addFont(
        File('$root/$name').readAsBytes().then(ByteData.sublistView),
      );
    }
    await loader.load();
  }
  final mono = FontLoader('ProbeNerd');
  mono.addFont(
    rootBundle.load(
      'assets/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf',
    ),
  );
  await mono.load();
}

void main() {
  for (final width in [320.0, 390.0]) {
    testWidgets(
      'mobile SSH trust and rotation anchors at $width',
      (tester) async {
        final peer = (await tester.runAsync(RotationPeer.start))!;
        addTearDown(() => tester.runAsync(peer.stop));
        final padding = width == 320
            ? const FakeViewPadding(top: 24, bottom: 24)
            : const FakeViewPadding(top: 47, bottom: 34);
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = Size(width, width == 320 ? 640 : 844);
        tester.view.padding = padding;
        tester.view.viewPadding = padding;
        addTearDown(tester.view.reset);
        final tokens = (await tester.runAsync(() async {
          await (anchorFonts ??= loadAnchorFonts(
            Platform.environment['HERDR_AUTH_ANCHOR_FONT_DIR']!,
          ));
          return DesignTokens.load();
        }))!;
        final theme = tokens.theme.copyWith(
          textTheme: tokens.theme.textTheme.apply(
            fontFamily: 'AnchorSanFrancisco',
            fontFamilyFallback: ['AnchorPingFang'],
          ),
          primaryTextTheme: tokens.theme.primaryTextTheme.apply(
            fontFamily: 'AnchorSanFrancisco',
            fontFamilyFallback: ['AnchorPingFang'],
          ),
        );
        final catalog = HostCatalog(
          storage: MemoryCatalogStorage(),
          clock: () => 1000,
        );
        await tester.pumpWidget(
          MaterialApp(
            theme: theme,
            home: HostCatalogPage(
              tokens: tokens,
              catalog: catalog,
              offlineBuilder: (_) => const SizedBox(),
            ),
          ),
        );
        await tester.pumpAndSettle();
        Finder key(String id) => find.byKey(ValueKey(id));
        final margin = width == 320 ? 16.0 : 24.0;
        final top = padding.top;
        final promptRect = Rect.fromLTWH(
          margin,
          top + 278,
          width - 2 * margin,
          52,
        );
        final approvedRect = Rect.fromLTWH(
          margin,
          top + 138,
          width - 2 * margin,
          44,
        );
        final headerRect = Rect.fromLTWH(0, top, width, 56);
        final backRect = Rect.fromLTWH(margin - 8, top + 6, 44, 44);
        void measure(
          String state,
          String anchor,
          Finder finder,
          Rect expected, {
          bool header = false,
          bool interactive = false,
        }) {
          expect(finder, findsOneWidget, reason: '$state $anchor');
          final raw = tester.getRect(finder);
          final actual = header
              ? Rect.fromLTWH(
                  raw.left,
                  raw.top + top,
                  raw.width,
                  raw.height - top,
                )
              : raw;
          final hit = finder
              .hitTestable(at: Alignment.center)
              .evaluate()
              .isNotEmpty;
          debugPrint(
            'AUTH_ANCHOR ${jsonEncode({
              'state': state,
              'width': width,
              'anchor': anchor,
              'raw': [raw.left, raw.top, raw.width, raw.height],
              'actual': [actual.left, actual.top, actual.width, actual.height],
              'expected': [expected.left, expected.top, expected.width, expected.height],
              'centerHit': hit,
            })}',
          );
          for (final delta in [
            actual.left - expected.left,
            actual.top - expected.top,
            actual.width - expected.width,
            actual.height - expected.height,
          ]) {
            expect(
              delta.abs(),
              lessThanOrEqualTo(2),
              reason: '$state $anchor at $width',
            );
          }
          if (interactive)
            expect(hit, isTrue, reason: '$state $anchor center hit');
        }

        Finder prompt() => find
            .ancestor(
              of: find.text('请通过服务器控制台或向管理员独立核对。\n算法和完整指纹一致后，再确认继续。'),
              matching: find.byType(SizedBox),
            )
            .first;
        Finder approved() => find
            .ancestor(
              of: find.text('本次主机密钥已确认'),
              matching: find.byType(Container),
            )
            .first;
        void header(String stage, {bool showBack = true}) {
          measure(
            stage,
            'app-header',
            find.byType(AppBar),
            headerRect,
            header: true,
          );
          if (showBack) {
            measure(
              stage,
              'back',
              find.byType(BackButton),
              backRect,
              interactive: true,
            );
          } else {
            expect(find.byType(BackButton), findsNothing);
          }
        }

        await tester.tap(key('hosts-direct-ssh'));
        await tester.pumpAndSettle();
        await tester.enterText(key('direct-host'), '127.0.0.1');
        await tester.enterText(key('direct-port'), '${peer.port}');
        await tester.enterText(key('direct-user'), 'fixture');
        await tester.pump();
        await tester.tap(key('direct-probe'));
        await tester.pump();
        await waitFor(tester, key('direct-trust-key'));
        await tester.pumpAndSettle();
        measure('trust', 'independent-verification', prompt(), promptRect);
        expect(peer.sawAuthentication, isFalse);
        await tester.tap(key('direct-trust-key'));
        await tester.pumpAndSettle();
        final dynamic state = tester.state(find.byType(DirectSshPage));
        final oldFingerprint = state.fingerprint;
        expect(state.secret.text, isEmpty);
        measure('password', 'trust-approved', approved(), approvedRect);
        await tester.tap(key('direct-auth-key'));
        await tester.pumpAndSettle();
        expect(state.secret.text, isEmpty);
        measure('private-key', 'trust-approved', approved(), approvedRect);
        await tester.tap(key('direct-auth-password'));
        await tester.pumpAndSettle();
        await tester.enterText(key('direct-secret'), 'temporary');
        await tester.pump();
        await tester.ensureVisible(key('direct-connect'));
        await tester.tap(key('direct-connect'));
        await tester.pump();
        await waitFor(tester, key('direct-host-key-change'));
        await tester.pumpAndSettle();
        expect(state.secret.text, isEmpty);
        expect(peer.sawAuthentication, isFalse);
        final newFingerprint = state.hostKeyChange.newFingerprint as String;
        expect(state.hostKeyChange.oldFingerprint, oldFingerprint);
        expect(newFingerprint, isNot(oldFingerprint));
        header('key-changed', showBack: false);
        await tester.tap(key('direct-host-key-cancel'));
        await tester.pumpAndSettle();
        expect(state.fingerprint, oldFingerprint);
        expect(state.hostKeyReviewRequired, isTrue);
        header('previous-trust');
        await tester.tap(key('direct-probe'));
        await tester.pump();
        await waitFor(tester, key('direct-trust-key'));
        await tester.pumpAndSettle();
        expect(
          tester.widget<SelectableText>(key('direct-key-fingerprint')).data,
          newFingerprint,
        );
        header('recheck-trust');
        measure(
          'recheck-trust',
          'independent-verification',
          prompt(),
          promptRect,
        );
        await tester.tap(key('direct-trust-cancel'));
        await tester.pumpAndSettle();
        expect(state.fingerprint, oldFingerprint);
        expect(state.hostKeyReviewRequired, isTrue);
        expect(peer.sawAuthentication, isFalse);
        expect(
          RegExp(
            r'(^|\n)(AUTH|PUBLICKEY|PTY) ',
            multiLine: true,
          ).hasMatch(peer.logs.join()),
          isFalse,
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        catalog.dispose();
      },
      variant: TargetPlatformVariant.only(TargetPlatform.iOS),
      skip:
          Platform.environment['HERDR_FIXTURE_PYTHON'] == null ||
          Platform.environment['HERDR_AUTH_ANCHOR_FONT_DIR'] == null,
    );
  }
}
