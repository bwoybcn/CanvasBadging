// SPDX-License-Identifier: AGPL-3.0-or-later
// Runs the 1EdTech OB 3.0 inspector (github.com/1EdTech/digital-credentials-public-validator)
// over credentials issued by OpenCredential. CI copies this file into a pinned checkout of that
// repository (inspector-vc test sources) and runs it with OC_CONFORMANCE_ACTIVE_DIR and
// OC_CONFORMANCE_REVOKED_DIR pointing at directories of issued credential JSON files.
package org.oneedtech.inspect.vc;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.google.common.io.CharSource;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.oneedtech.inspect.core.Inspector.Behavior;
import org.oneedtech.inspect.core.report.Report;
import org.oneedtech.inspect.test.PrintHelper;
import org.oneedtech.inspect.util.resource.ResourceType;
import org.oneedtech.inspect.util.resource.StringResource;

public class OpenCredentialConformanceTest {

  private static List<Path> files(String env) throws IOException {
    String dir = System.getenv(env);
    if (dir == null) return List.of();
    try (Stream<Path> s = Files.list(Path.of(dir))) {
      return s.filter(p -> p.toString().endsWith(".json")).sorted().toList();
    }
  }

  private record Result(Report report, String printed) {}

  private static Result inspect(Path file) throws Exception {
    OB30Inspector inspector =
        new OB30Inspector.Builder().set(Behavior.TEST_INCLUDE_SUCCESS, true).build();
    String json = Files.readString(file, StandardCharsets.UTF_8);
    Report report =
        inspector.run(new StringResource(CharSource.wrap(json), file.toString(), ResourceType.JSON));
    // Capture the human-readable report so we can check *why* it passed or failed.
    PrintStream out = System.out;
    ByteArrayOutputStream buf = new ByteArrayOutputStream();
    System.setOut(new PrintStream(buf, true, StandardCharsets.UTF_8));
    try {
      PrintHelper.print(report, true);
    } finally {
      System.setOut(out);
    }
    String printed = buf.toString(StandardCharsets.UTF_8);
    System.out.println("=== " + file.getFileName() + " ===");
    System.out.println(printed);
    return new Result(report, printed);
  }

  @Test
  void activeCredentialsAreValid() throws Exception {
    List<Path> active = files("OC_CONFORMANCE_ACTIVE_DIR");
    assertFalse(active.isEmpty(), "no active credentials supplied");
    for (Path f : active) {
      Result r = inspect(f);
      assertTrue(r.report().asBoolean(), f + " should pass the 1EdTech OB 3.0 inspector");
      assertTrue(r.printed().contains("Credential is not revoked."), f + ": status not checked");
    }
  }

  @Test
  void revokedCredentialsAreRejected() throws Exception {
    List<Path> revoked = files("OC_CONFORMANCE_REVOKED_DIR");
    assertFalse(revoked.isEmpty(), "no revoked credentials supplied");
    for (Path f : revoked) {
      Result r = inspect(f);
      assertFalse(r.report().asBoolean(), f + " is revoked and should not pass");
      assertTrue(
          r.printed().contains("Credential has been revoked"), f + ": failed for another reason");
    }
  }
}
