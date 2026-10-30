import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:terminal_view/terminal_view.dart';

/// Shared Penpot v2 palette. Missing or malformed tokens fail during startup;
/// neither renderer silently substitutes its own brand or ANSI palette.
class DesignTokens {
  DesignTokens(this.data);
  final Map<String, dynamic> data;

  static Future<DesignTokens> load() async => DesignTokens(jsonDecode(
    await rootBundle.loadString('assets/shared/design-tokens-v2.json')) as Map<String, dynamic>);

  Color parse(dynamic value) {
    if (value is! String || !RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(value)) {
      throw FormatException('Invalid shared color token: $value');
    }
    return Color(0xff000000 | int.parse(value.substring(1), radix: 16));
  }

  Color color(String name) => parse((data['colors'] as Map)[name]);
  Color ansi(String name) => parse((data['terminal']['ansi'] as Map)[name]);

  ThemeData get theme {
    final scheme = ColorScheme.fromSeed(seedColor: color('brand')).copyWith(
      primary: color('brand'), onPrimary: color('textInverse'),
      primaryContainer: color('brandSoft'), onPrimaryContainer: color('brandHover'),
      secondary: color('brand'), onSecondary: color('textInverse'),
      secondaryContainer: color('brandSoft'), onSecondaryContainer: color('brandHover'),
      surface: color('card'), onSurface: color('textPrimary'),
      onSurfaceVariant: color('textSecondary'), outline: color('borderStrong'),
      error: color('dangerText'), onError: color('textInverse'),
    );
    return ThemeData(useMaterial3: true, colorScheme: scheme,
      scaffoldBackgroundColor: color('canvas'),
      focusColor: color('brandSoft'),
      appBarTheme: AppBarTheme(backgroundColor: color('card'),
        foregroundColor: color('textPrimary'), surfaceTintColor: Colors.transparent,
        titleTextStyle: TextStyle(color: color('textPrimary'), fontSize: 18, fontWeight: FontWeight.w700)),
      textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(
        minimumSize: const Size(44, 44), tapTargetSize: MaterialTapTargetSize.padded)),
      filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(
        minimumSize: const Size(44, 44), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)))),
      chipTheme: ChipThemeData(selectedColor: color('brandSoft'),
        backgroundColor: color('card'), side: BorderSide(color: color('borderStrong')),
        labelStyle: TextStyle(color: color('textPrimary')), showCheckmark: false),
      inputDecorationTheme: InputDecorationTheme(filled: true, fillColor: color('card'),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: color('brand'), width: 2))),
    );
  }

  TerminalTheme get terminalTheme => TerminalTheme(
    cursor: color('termCursor'), cursorAccent: color('termBg'),
    selection: color('brand').withAlpha(0x55),
    foreground: color('termText'), background: color('termBg'),
    black: ansi('black'), white: ansi('white'), red: ansi('red'),
    green: ansi('green'), yellow: ansi('yellow'), blue: ansi('blue'),
    magenta: ansi('magenta'), cyan: ansi('cyan'),
    brightBlack: ansi('brightBlack'), brightRed: ansi('brightRed'),
    brightGreen: ansi('brightGreen'), brightYellow: ansi('brightYellow'),
    brightBlue: ansi('brightBlue'), brightMagenta: ansi('brightMagenta'),
    brightCyan: ansi('brightCyan'), brightWhite: ansi('brightWhite'),
    searchHitBackground: color('termWarning'),
    searchHitBackgroundCurrent: color('termSuccess'), searchHitForeground: color('termBg'),
  );
}
