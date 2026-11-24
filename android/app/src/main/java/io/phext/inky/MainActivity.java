package io.phext.inky;

import android.app.Activity;
import android.content.res.AssetManager;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Inky for Android - reachable rung.
 *
 * A minimal Chaquopy shell around the unmodified inky engine (inky.py,
 * bundled in src/main/python together with protect.txt and words-en.txt).
 * One input box, one button ("Massage my typos"), and an output area
 * showing (a) the corrected text and (b) inky's analysis report
 * (flagged hippos, scored candidate lines with tiers).
 * The full Kotlin keyboard port remains the charted moonshot.
 */
public class MainActivity extends Activity {

    private EditText input;
    private TextView correctedOut;
    private TextView analysisOut;
    private Button runButton;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private File dataDir;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Copy the bundled engine data files out of assets into private
        // storage so the runner can point inky's --dict / --protect at them.
        dataDir = new File(getFilesDir(), "inky-data");
        copyAsset("protect.txt", dataDir);
        copyAsset("words-en.txt", dataDir);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("inky - it massages your typos; it does not correct you");
        title.setTextSize(18);
        root.addView(title);

        input = new EditText(this);
        input.setHint("Write or paste your text here...");
        input.setMinLines(6);
        input.setGravity(android.view.Gravity.TOP);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        root.addView(input);

        runButton = new Button(this);
        runButton.setText("Massage my typos");
        root.addView(runButton);

        TextView correctedLabel = new TextView(this);
        correctedLabel.setText("Corrected text:");
        correctedLabel.setTextSize(16);
        root.addView(correctedLabel);

        correctedOut = new TextView(this);
        correctedOut.setTextIsSelectable(true);
        root.addView(correctedOut);

        TextView analysisLabel = new TextView(this);
        analysisLabel.setText("Analysis:");
        analysisLabel.setTextSize(16);
        root.addView(analysisLabel);

        analysisOut = new TextView(this);
        analysisOut.setTextIsSelectable(true);
        root.addView(analysisOut);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);

        runButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                runInky();
            }
        });
    }

    private void copyAsset(String name, File dir) {
        try {
            if (!dir.exists()) dir.mkdirs();
            File out = new File(dir, name);
            if (out.exists() && out.length() > 0) return;
            AssetManager am = getAssets();
            InputStream in = am.open(name);
            FileOutputStream fos = new FileOutputStream(out);
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) fos.write(buf, 0, n);
            fos.close();
            in.close();
        } catch (Exception e) {
            // Runner falls back to the copies bundled beside inky.py.
        }
    }

    private void runInky() {
        final String text = input.getText().toString();
        runButton.setEnabled(false);
        correctedOut.setText("");
        analysisOut.setText("inky is thinking...");
        executor.execute(new Runnable() {
            @Override
            public void run() {
                String corrected = "";
                String report = "";
                try {
                    if (!Python.isStarted()) {
                        Python.start(new AndroidPlatform(MainActivity.this));
                    }
                    Python py = Python.getInstance();
                    PyObject module = py.getModule("inky_runner");
                    String workdir = new File(getFilesDir(), "inky-work").getAbsolutePath();
                    PyObject result = module.callAttr("run", text, workdir, dataDir.getAbsolutePath());
                    String all = result.toString();
                    String sep = "\n<<<INKY_REPORT>>>\n";
                    int idx = all.indexOf(sep);
                    if (idx >= 0) {
                        corrected = all.substring(0, idx);
                        report = all.substring(idx + sep.length());
                    } else {
                        corrected = all;
                        report = "(no report returned)";
                    }
                } catch (final Exception e) {
                    corrected = "";
                    report = "inky failed: " + e;
                }
                final String fc = corrected;
                final String fr = report;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        correctedOut.setText(fc);
                        analysisOut.setText(fr);
                        runButton.setEnabled(true);
                    }
                });
            }
        });
    }
}
