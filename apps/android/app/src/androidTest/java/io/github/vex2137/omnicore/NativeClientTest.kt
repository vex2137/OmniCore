package io.github.vex2137.omnicore

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Real native widgets/network/Keystore on an emulator; controlled API responses, not inference. */
@RunWith(AndroidJUnit4::class)
class NativeClientTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    private val token = "a".repeat(48)
    @Volatile private var exists = false
    @Volatile private var title = "New conversation"
    @Volatile private var selectedModelId = "m1"
    @Volatile private var content = ""
    @Volatile private var generationNumber = 0
    @Volatile private var jobState = "running"
    @Volatile private var cancelCalls = 0
    @Volatile private var downloadState = "running"
    @Volatile private var downloaded = false

    private fun transfer() =
        """{"id":"d","source":{"repository":"owner/repo","revision":"abc","filename":"model.gguf","size_bytes":123},"state":"$downloadState","received_bytes":60,"percent":48}"""

    private fun conversation() = """{"id":"c1","title":"$title","model_id":"$selectedModelId"}"""

    private fun job(
        state: String = jobState,
        sequence: Int = 1,
        answer: String = "Hello from backend",
    ) =
        """{"id":"j$generationNumber","conversation_id":"c1","model_id":"$selectedModelId","state":"$state","content":"$answer","sequence":$sequence}"""

    private fun json(body: String) =
        MockResponse().setHeader("Content-Type", "application/json").setBody(body)

    @Test
    fun nativeConnectionChatStreamingCancelHistoryLocalesThemesAndKeystore() {
        val server = MockWebServer()
        server.dispatcher =
            object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    if (request.getHeader("Authorization") != "Bearer $token")
                        return json("{}").setResponseCode(401)
                    val path = request.requestUrl!!.encodedPath
                    return when {
                        path == "/api/v1/health" ->
                            json("""{"status":"ok","version":"test","database_version":1}""")
                        path == "/api/v1/text/downloads" && request.method == "POST" -> {
                            downloaded = true
                            json(transfer())
                        }
                        path == "/api/v1/text/downloads/d/cancel" -> {
                            downloadState = "cancelled"
                            json(transfer())
                        }
                        path == "/api/v1/text/downloads/d/resume" -> {
                            downloadState = "running"
                            json(transfer())
                        }
                        path == "/api/v1/text/downloads" ->
                            json(if (downloaded) "[${transfer()}]" else "[]")
                        path == "/api/v1/text/diagnostics" -> json("""{"generations":[]}""")
                        path == "/api/v1/text/huggingface/files" ->
                            json(
                                """[{"repository":"owner/repo","revision":"abc","filename":"model.gguf","size_bytes":123,"license":"test"}]"""
                            )
                        path == "/api/v1/text/models" ->
                            json(
                                """[{"id":"m1","name":"Fixture GGUF","backend":"llama.cpp","format":"GGUF","size_bytes":1000,"compatibility":"unverified"},{"id":"m2","name":"Second GGUF","backend":"llama.cpp","format":"GGUF","compatibility":"unverified"}]"""
                            )
                        path == "/api/v1/text/engines" ->
                            json(
                                """[{"info":{"id":"llama.cpp","version":"controlled API fixture","available":true},"gpu_devices":[]}]"""
                            )
                        path == "/api/v1/text/conversations" && request.method == "POST" -> {
                            exists = true
                            json(conversation()).setResponseCode(201)
                        }
                        path == "/api/v1/text/conversations" ->
                            json(if (exists) "[${conversation()}]" else "[]")
                        path == "/api/v1/text/conversations/c1" && request.method == "PATCH" -> {
                            val patch =
                                WireJson.parseToJsonElement(request.body.readUtf8()).jsonObject
                            patch["title"]?.let { title = it.jsonPrimitive.content }
                            patch["model_id"]?.let { selectedModelId = it.jsonPrimitive.content }
                            json(conversation())
                        }
                        path == "/api/v1/text/conversations/c1" && request.method == "DELETE" -> {
                            exists = false
                            content = ""
                            json("{}")
                        }
                        path.endsWith("/messages") ->
                            json(
                                if (content.isEmpty()) "[]"
                                else
                                    """[{"id":"u","role":"user","content":"$content"},{"id":"a","role":"assistant","content":"Hello from backend","generation_id":"j$generationNumber","status":"${if(jobState == "cancelled") "cancelled" else "completed"}"}]"""
                            )
                        path.endsWith("/generations") && request.method == "POST" -> {
                            content =
                                WireJson.parseToJsonElement(request.body.readUtf8())
                                    .jsonObject["content"]!!
                                    .jsonPrimitive
                                    .content
                            generationNumber++
                            jobState = "running"
                            json(job(answer = "", sequence = 0)).setResponseCode(202)
                        }
                        path.endsWith("/cancel") -> {
                            cancelCalls++
                            jobState = "cancelled"
                            json(job("cancelled", 99))
                        }
                        path.endsWith("/stream") -> {
                            assertEquals(
                                "false",
                                request.requestUrl!!.queryParameter("cancel_on_disconnect"),
                            )
                            val stream =
                                if (generationNumber == 1) {
                                    jobState = "completed"
                                    "data: ${job("running", 1, "Hello")}\n\ndata: ${job("completed", 2)}\n\n"
                                } else "data: ${job(jobState, 1, "Hello")}\n\n"
                            MockResponse()
                                .setHeader("Content-Type", "text/event-stream")
                                .setBody(stream)
                                .throttleBody(32, 30, TimeUnit.MILLISECONDS)
                        }
                        path.startsWith("/api/v1/text/generations/") -> json(job())
                        else -> json("{}")
                    }
                }
            }
        server.start()
        try {
            compose.onNodeWithTag("nav_3").performClick()
            compose.onNodeWithTag("url").performTextClearance()
            compose.onNodeWithTag("url").performTextInput(server.url("/").toString().trimEnd('/'))
            compose.onNodeWithTag("token").performTextInput(token)
            compose.onNodeWithTag("trusted_lan").performScrollTo().performClick()
            compose.onNodeWithTag("connect").performScrollTo().assertIsEnabled().performClick()
            compose.waitUntil(15000) {
                compose.onAllNodesWithText("Connected").fetchSemanticsNodes().isNotEmpty() &&
                    compose.onAllNodesWithTag("busy").fetchSemanticsNodes().isEmpty()
            }
            val context = InstrumentationRegistry.getInstrumentation().targetContext
            val preferences = context.getSharedPreferences("omnicore", 0)
            assertFalse(preferences.all.toString().contains(token))
            assertEquals(token, SecureSettings(context).readToken())
            assertTrue(preferences.getString("token_cipher", "").orEmpty().isNotEmpty())
            compose.onNodeWithTag("nav_0").performClick()
            compose.onNodeWithTag("home_new").performScrollTo().performClick()
            compose.waitUntil(10000) {
                compose
                    .onAllNodes(hasTestTag("composer") and isEnabled())
                    .fetchSemanticsNodes()
                    .isNotEmpty() &&
                    compose.onAllNodesWithTag("busy").fetchSemanticsNodes().isEmpty()
            }
            compose.onNodeWithText("Fixture GGUF · llama.cpp").performClick()
            compose.onNodeWithText("Second GGUF · llama.cpp").performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithTag("busy").fetchSemanticsNodes().isEmpty()
            }
            assertEquals("m2", selectedModelId)
            compose.onNodeWithTag("composer").performTextInput("Hello")
            compose.onNodeWithTag("send").performClick()
            compose.waitUntil(15000) {
                compose.onAllNodesWithText("Completed").fetchSemanticsNodes().isNotEmpty()
            }
            // Completion can arrive before the LazyColumn finishes its automatic scroll.
            compose.waitUntil(10000) { compose.onNodeWithText("Hello from backend").isDisplayed() }
            compose.onNodeWithText("Hello from backend").assertIsDisplayed()
            compose.onNodeWithTag("composer").performTextInput("More")
            compose.onNodeWithTag("send").performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithTag("stop").fetchSemanticsNodes().isNotEmpty()
            }
            compose.activityRule.scenario.moveToState(androidx.lifecycle.Lifecycle.State.CREATED)
            assertEquals(0, cancelCalls)
            assertEquals("running", jobState)
            compose.activityRule.scenario.moveToState(androidx.lifecycle.Lifecycle.State.RESUMED)
            compose.activityRule.scenario.recreate()
            compose.waitUntil(15000) {
                compose
                    .onAllNodes(hasTestTag("stop") and isEnabled())
                    .fetchSemanticsNodes()
                    .isNotEmpty()
            }
            compose.onNodeWithTag("stop").performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithText("Cancelled").fetchSemanticsNodes().isNotEmpty()
            }
            compose.waitUntil(10000) {
                compose.onAllNodesWithTag("busy").fetchSemanticsNodes().isEmpty()
            }
            compose.onNodeWithContentDescription("Rename").performClick()
            compose.onNodeWithText("Conversation title").performTextClearance()
            compose.onNodeWithText("Conversation title").performTextInput("My history")
            compose.onNodeWithText("Save", useUnmergedTree = true).performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithText("My history").fetchSemanticsNodes().isNotEmpty()
            }
            val capture =
                InstrumentationRegistry.getInstrumentation()
                    .uiAutomation
                    .executeShellCommand("screencap -p /sdcard/Download/omnicore-android-chat.png")
            android.os.ParcelFileDescriptor.AutoCloseInputStream(capture).use { it.readBytes() }
            compose.onNodeWithTag("nav_2").performClick()
            compose.onNodeWithTag("hub_toggle").performScrollTo().performClick()
            compose.onNodeWithTag("hub_query").performScrollTo().performTextInput("owner/repo")
            compose.onNodeWithTag("hub_files").performScrollTo().performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithTag("download_file").fetchSemanticsNodes().isNotEmpty()
            }
            compose.onNodeWithTag("download_file").performScrollTo().performClick()
            compose.onNodeWithTag("download_confirm").performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithTag("download_cancel").fetchSemanticsNodes().isNotEmpty()
            }
            compose.onNodeWithTag("download_cancel").performScrollTo().performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithTag("download_resume").fetchSemanticsNodes().isNotEmpty()
            }
            compose.onNodeWithTag("download_resume").performScrollTo().performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithTag("download_cancel").fetchSemanticsNodes().isNotEmpty()
            }
            assertEquals("running", downloadState)
            compose.onNodeWithTag("nav_4").performClick()
            compose
                .onNodeWithText(
                    "Connection and engine diagnostics. Tokens and conversation content are never logged."
                )
                .assertExists()
            compose.onNodeWithTag("nav_3").performClick()
            compose
                .onNodeWithText("System", useUnmergedTree = true)
                .performScrollTo()
                .performClick()
            compose.onNodeWithText("Dark", useUnmergedTree = true).performClick()
            compose
                .onNodeWithText("English", useUnmergedTree = true)
                .performScrollTo()
                .performClick()
            compose.onNodeWithText("Polski", useUnmergedTree = true).performClick()
            compose.waitUntil(10000) {
                compose.onAllNodesWithText("Zapisz i połącz").fetchSemanticsNodes().isNotEmpty()
            }
            assertEquals("dark", SecureSettings(context).theme)
            assertEquals("pl-PL", SecureSettings(context).language)
            compose
                .onNodeWithText("Polski", useUnmergedTree = true)
                .performScrollTo()
                .performClick()
            compose.onNodeWithText("English", useUnmergedTree = true).performClick()
            compose.onNodeWithTag("nav_1").performClick()
            compose.onNodeWithContentDescription("Delete").performClick()
            compose.onNode(hasText("Confirm") and hasClickAction()).performClick()
            compose.waitUntil(10000) {
                !exists &&
                    compose.onAllNodesWithTag("busy").fetchSemanticsNodes().isEmpty() &&
                    compose
                        .onAllNodesWithText("Choose a conversation")
                        .fetchSemanticsNodes()
                        .isNotEmpty()
            }
            compose.onNodeWithText("Hello from backend").assertDoesNotExist()
        } catch (failure: Throwable) {
            // Only geometry and fixture UI are captured; never dump password semantics or headers.
            val reply =
                compose.onAllNodesWithText("Hello from backend").fetchSemanticsNodes().firstOrNull()
            val list = compose.onAllNodesWithTag("messages").fetchSemanticsNodes().firstOrNull()
            println("Chat geometry: reply=${reply?.boundsInRoot}, list=${list?.boundsInRoot}")
            val capture =
                InstrumentationRegistry.getInstrumentation()
                    .uiAutomation
                    .executeShellCommand(
                        "screencap -p /sdcard/Download/omnicore-android-failure.png"
                    )
            android.os.ParcelFileDescriptor.AutoCloseInputStream(capture).use { it.readBytes() }
            throw failure
        } finally {
            server.shutdown()
        }
    }
}
