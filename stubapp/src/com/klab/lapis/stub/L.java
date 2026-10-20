package com.klab.lapis.stub;

import android.util.Log;

public class L {
    public static void log(Object ctx, String s) { Log.i("LapisStub", s); }
    public static void log(String s) { Log.i("LapisStub", s); }
}
