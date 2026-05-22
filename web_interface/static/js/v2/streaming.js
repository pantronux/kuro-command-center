export function setStatus(text, state = 'ready') {
    const bar = document.getElementById('v2StatusBar');
    const label = document.getElementById('v2StatusText');
    if (bar) bar.dataset.state = state;
    if (label) label.textContent = text;
}

function parseSseBlocks(buffer) {
    const blocks = buffer.split(/\n\n/);
    return {
        complete: blocks.slice(0, -1),
        tail: blocks[blocks.length - 1] || '',
    };
}

function parseEvent(block) {
    const event = { event: 'message', data: '' };
    const dataLines = [];
    block.split(/\n/).forEach((line) => {
        if (line.startsWith('event: ')) event.event = line.slice(7).trim();
        if (line.startsWith('data: ')) dataLines.push(line.slice(6));
    });
    const dataText = dataLines.join('\n').trim();
    if (dataText === '[DONE]') {
        event.data = { done: true };
        return event;
    }
    try {
        event.data = JSON.parse(dataText);
    } catch (_) {
        event.data = { text: dataText };
    }
    return event;
}

export async function streamChat({
    message,
    persona,
    chatId,
    settings,
    onToken,
    onEvent,
    onError,
    onDone,
    attempt = 0,
}) {
    const form = new FormData();
    form.append('message', message);
    form.append('persona', persona || 'consultant');
    if (chatId) form.append('chat_id', chatId);
    if (settings?.runtime_id) form.append('runtime_id', settings.runtime_id);

    setStatus('Streaming', 'busy');
    let response;
    try {
        response = await fetch('/api/chat/v2/stream', {
            method: 'POST',
            credentials: 'include',
            body: form,
        });
        if (response.status === 404) {
            response = await fetch('/api/chat/stream', {
                method: 'POST',
                credentials: 'include',
                body: form,
                headers: chatId ? { 'X-Chat-Session': chatId } : {},
            });
        }
        if (!response.ok) throw new Error(`Stream failed (${response.status})`);
    } catch (error) {
        if (attempt < 2) {
            await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)));
            return streamChat({ message, persona, chatId, settings, onToken, onEvent, onError, onDone, attempt: attempt + 1 });
        }
        setStatus(error.message || 'Stream error', 'error');
        onError?.(error);
        return;
    }

    if (!response.body) {
        setStatus('Stream unavailable', 'error');
        onError?.(new Error('Stream unavailable'));
        return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseBlocks(buffer);
        buffer = parsed.tail;
        parsed.complete.forEach((block) => {
            const event = parseEvent(block);
            onEvent?.(event);
            const payload = event.data?.data || event.data || {};
            if (event.event === 'token' || event.event === 'chunk') {
                onToken?.(payload.text || payload.delta || payload.content || '');
            }
            if (event.event === 'error') {
                const messageText = payload.message || payload.error || event.data?.error || 'Stream error';
                setStatus(messageText, 'error');
                onError?.(new Error(messageText));
            }
            if (event.event === 'done' || event.event === 'complete') {
                setStatus('Ready', 'ready');
                onDone?.(event);
            }
        });
    }

    if (buffer.trim()) {
        const event = parseEvent(buffer);
        onEvent?.(event);
    }
    setStatus('Ready', 'ready');
}
