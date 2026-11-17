package io.github.vex2137.omnicore

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StatisticsUiTest {
    @get:Rule val compose = createComposeRule()

    private val sampleStats =
        GenerationStatistics(
            gpuOffloadedLayers = 25,
            executionDevice = "Mali-G720 MC7",
            inputTokens = 14,
            outputTokens = 61,
            ttftSeconds = 7.16,
            firstAnswerSeconds = 7.16,
            generationSeconds = 11.63,
            modelLoadSeconds = 5.35,
            contextUsedTokens = 75,
            contextLimitTokens = 2048,
            finishReason = "stop",
            tokensPerSecond = 13.43,
        )

    @Test
    fun compactStatisticsFooterExpandsAndCollapsesWithoutShowingDuringStreaming() {
        compose.setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                MessageBubble(
                    role = "assistant",
                    content = "Hello from OmniCore.",
                    modelName = "LFM3 1.7B",
                    statistics = sampleStats,
                    isStreaming = false,
                )
            }
        }
        compose.onNodeWithTag("stats_compact").assertIsDisplayed()
        compose.onNodeWithTag("stats_toggle").assertIsDisplayed()
        compose.onNodeWithTag("stats_expanded_panel").assertDoesNotExist()

        compose.onNodeWithTag("stats_toggle").performClick()
        compose.onNodeWithTag("stats_expanded_panel").assertIsDisplayed()
        compose.onNodeWithText("75/2048 (3%)", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Mali-G720 MC7", substring = true).assertIsDisplayed()

        compose.onNodeWithTag("stats_toggle").performClick()
        compose.onNodeWithTag("stats_expanded_panel").assertDoesNotExist()
    }

    @Test
    fun streamingHidesFooterUntilTerminal() {
        compose.setContent {
            MaterialTheme {
                MessageBubble(
                    role = "assistant",
                    content = "Partial stream",
                    modelName = "LFM3 1.7B",
                    statistics = sampleStats,
                    isStreaming = true,
                )
            }
        }
        compose.onNodeWithTag("stats_compact").assertDoesNotExist()
        compose.onNodeWithTag("stats_toggle").assertDoesNotExist()
    }
}
