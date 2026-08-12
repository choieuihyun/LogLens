package io.loglens.core;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * 날짜별 파일 싱크. 순수 자바 — 호스트 앱의 파일 유틸에 의존하지 않는다(기획서 §5).
 *
 * <p>logcat 은 링버퍼라 금방 밀린다. 재현이 어려운 버그는 파일에 남아 있어야 잡힌다.
 * 뷰어는 {@code --source file} 로 이 파일을 그대로 재생할 수 있다 — 같은 줄 규격이니까.
 */
public final class FileSink implements Sink {

    private final File dir;
    private final String prefix;
    private final int keepDays;

    private String currentDay;
    private BufferedWriter writer;

    // withInitial() 은 안드로이드 API 26+ 다 (LineFormat 의 주석 참고). minSdk 21 을 지킨다.
    private static final ThreadLocal<SimpleDateFormat> DAY = new ThreadLocal<SimpleDateFormat>() {
        @Override protected SimpleDateFormat initialValue() {
            return new SimpleDateFormat("yyyy-MM-dd", Locale.US);
        }
    };

    public FileSink(File dir) { this(dir, "app", 7); }

    /**
     * @param dir      로그 디렉터리
     * @param prefix   파일명 접두사 → {@code app-2026-08-12.log}
     * @param keepDays 이 일수보다 오래된 파일은 지운다 (0 이면 안 지움)
     */
    public FileSink(File dir, String prefix, int keepDays) {
        this.dir = dir;
        this.prefix = prefix;
        this.keepDays = keepDays;
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        purgeOld();
    }

    @Override
    public synchronized void write(Level level, String tag, String body) {
        try {
            roll();
            if (writer == null) return;
            writer.write(LineFormat.render(level, tag, body));
            writer.newLine();
            writer.flush();
        } catch (IOException ignored) {
            // 파일에 못 쓴다고 앱이 죽으면 안 된다.
        }
    }

    private void roll() throws IOException {
        String day = DAY.get().format(new Date());
        if (day.equals(currentDay) && writer != null) return;
        closeQuietly();
        currentDay = day;
        File f = new File(dir, prefix + "-" + day + ".log");
        writer = new BufferedWriter(new OutputStreamWriter(
                new FileOutputStream(f, true), StandardCharsets.UTF_8));
        purgeOld();
    }

    private void purgeOld() {
        if (keepDays <= 0) return;
        File[] files = dir.listFiles((d, name) ->
                name.startsWith(prefix + "-") && name.endsWith(".log"));
        if (files == null) return;
        long cutoff = System.currentTimeMillis() - keepDays * 86_400_000L;
        for (File f : files) {
            if (f.lastModified() < cutoff) {
                //noinspection ResultOfMethodCallIgnored
                f.delete();
            }
        }
    }

    @Override
    public synchronized void close() {
        closeQuietly();
    }

    private void closeQuietly() {
        if (writer != null) {
            try { writer.close(); } catch (IOException ignored) { }
            writer = null;
        }
    }
}
