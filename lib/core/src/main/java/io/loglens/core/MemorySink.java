package io.loglens.core;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** 테스트용. 찍힌 줄을 그대로 들고 있는다. */
public final class MemorySink implements Sink {

    private final List<String> lines = Collections.synchronizedList(new ArrayList<>());
    private final List<String> bodies = Collections.synchronizedList(new ArrayList<>());

    @Override
    public void write(Level level, String tag, String body) {
        bodies.add(body);
        lines.add(LineFormat.render(level, tag, body));
    }

    /** 접두사 포함 완성된 줄들. */
    public List<String> lines() { return new ArrayList<>(lines); }

    /** 본문만 (계약의 핵심 부분). */
    public List<String> bodies() { return new ArrayList<>(bodies); }

    public String lastBody() { return bodies.isEmpty() ? null : bodies.get(bodies.size() - 1); }

    public void clear() { lines.clear(); bodies.clear(); }

    public int size() { return bodies.size(); }
}
