package io.loglens.core;

import java.nio.charset.StandardCharsets;

/**
 * logcat 잘림 대비 — <b>코드포인트 경계</b>에서 자른다.
 *
 * <p>logcat 은 한 줄이 4KB 근처를 넘으면 알아서 잘라버린다. 우리가 먼저 자르지 않으면
 * 잘린 자리가 어디일지 모르고, 파서는 반쯤 뜯긴 줄을 받는다.
 *
 * <p>핵심은 <b>바이트로 세되 문자로 자르는</b> 것이다. 한글은 UTF-8 에서 3바이트라
 * 순진하게 {@code getBytes()[0..n]} 으로 자르면 코드포인트가 반으로 갈려서
 * 깨진 문자(mojibake)가 나오거나 디코딩이 실패한다. 이모지(서로게이트 페어)는 더 나쁘다.
 *
 * <p>여러 줄로 쪼개지 않는 이유: 한 줄 = 한 레코드가 계약이다(§4 I1).
 * 쪼개는 순간 파서가 두 번째 줄부터를 이해하지 못한다. 그래서 <b>통째로 자르고 표시한다.</b>
 */
public final class Truncator {

    /** 잘렸다는 표식. 뷰어가 이걸 보고 [cut] 배지를 단다. */
    public static final String MARK = "...[cut]";

    /** logcat 한 줄 payload 안전 한도(바이트). 실제 한계(~4076)보다 여유를 둔다. */
    public static final int DEFAULT_MAX_BYTES = 3800;

    private static final int MARK_BYTES = MARK.getBytes(StandardCharsets.UTF_8).length;

    private Truncator() {}

    public static String truncate(String s) {
        return truncate(s, DEFAULT_MAX_BYTES);
    }

    /**
     * {@code s} 의 UTF-8 바이트 길이가 {@code maxBytes} 이하가 되도록 자른다.
     * 자른 경우에만 {@link #MARK} 를 붙이며, 표식까지 포함해 {@code maxBytes} 를 넘지 않는다.
     */
    public static String truncate(String s, int maxBytes) {
        if (s == null) return null;
        if (maxBytes <= MARK_BYTES) return MARK;
        if (utf8Length(s) <= maxBytes) return s;

        int budget = maxBytes - MARK_BYTES;
        int bytes = 0;
        int i = 0;
        while (i < s.length()) {
            int cp = s.codePointAt(i);
            int w = utf8Width(cp);
            if (bytes + w > budget) break;
            bytes += w;
            i += Character.charCount(cp);   // 서로게이트 페어를 통째로 넘긴다
        }
        return s.substring(0, i) + MARK;
    }

    public static boolean isTruncated(String s) {
        return s != null && s.endsWith(MARK);
    }

    public static int utf8Length(String s) {
        int n = 0;
        for (int i = 0; i < s.length(); ) {
            int cp = s.codePointAt(i);
            n += utf8Width(cp);
            i += Character.charCount(cp);
        }
        return n;
    }

    private static int utf8Width(int cp) {
        if (cp < 0x80) return 1;
        if (cp < 0x800) return 2;
        if (cp < 0x10000) return 3;
        return 4;
    }
}
