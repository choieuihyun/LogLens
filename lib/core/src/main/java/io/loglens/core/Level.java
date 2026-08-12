package io.loglens.core;

/** 로그 레벨. 문자 하나가 곧 레코드에 찍히는 값이다. */
public enum Level {
    V('V'), D('D'), I('I'), W('W'), E('E');

    public final char c;

    Level(char c) {
        this.c = c;
    }

    /**
     * 릴리스 게이팅: V/D 는 디버그 빌드에서만, I/W/E 는 항상.
     * 기획서 §5 — 라이브러리는 앱의 빌드타입을 모르므로 {@code isDebug} 를 주입받는다.
     */
    public boolean enabled(boolean isDebug) {
        return isDebug || ordinal() >= I.ordinal();
    }
}
