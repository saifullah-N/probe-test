import { get, type Writable } from "svelte/store";

export function listenForChange<T>(writable: Writable<T>, cb: (value: T) => void) {
    const priorValue = get(writable);

    const unsubscribe = writable.subscribe((value) => {
        if (value !== priorValue) {
            unsubscribe();
            cb(value);
        }
    });
}

export function waitForChange<T>(writable: Writable<T>): Promise<T> {
    console.log("waiting for change: ",writable );

    return new Promise((resolve) => {
        listenForChange(writable, (value) => resolve(value));
    });
}
