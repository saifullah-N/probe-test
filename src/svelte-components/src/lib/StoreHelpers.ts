import { get, type Writable } from "svelte/store";

export function listenForChange<T>(writable: Writable<T>, cb: (value: T) => void) {
    const priorValue = get(writable);

    const unsubscribe = writable.subscribe((value) => {
        console.log({value , priorValue}, typeof(value))

        if (value !== priorValue) {
            console.log("inside if " , {value ,  priorValue} );
            
            unsubscribe();

            cb(value);
        }
    });
}

export function waitForChange<T>(writable: Writable<T>): Promise<T> {
    console.log("waiting for change: ",{writable} );

    return new Promise((resolve) => {
        console.log('23 before resolve');
        
        listenForChange(writable, (value) => resolve(value)); 
    });
}
//https://stackoverflow.com/questions/64862161/svelte-store-function-update?rq=1
//https://stackoverflow.com/questions/64862161/svelte-store-function-update?rq=1