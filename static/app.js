// Position in this user's personal ordering of the instances
let current_index = instance_index;
// Global index of the instance currently displayed (what gets stored in the database)
let current_instance_index = null;

// Fetch the initial model outputs based on the instance index
rendere_instance(current_index);

// Fetch the model outputs from the API and update the UI
async function rendere_instance(index) {
    const response = await fetch(`/api/model-outputs/${index}`);
    const data = await response.json();

    // if the response is error, show the out of range message
    if (data.error == "Index out of range") {
        show_alert(
            "You requested an out-of-range instance. You might have completed all the evaluations. Thank you for your contribution!", 
            "danger",
            insert_after_selector="#instance-info",
            timeout=1e10 // set timeout to a very large number so that the alert doesn't disappear
        );
        clear_all();
        current_instance_index = null;
        return;
    }

    clear_all();
    current_instance_index = data.instance_index;

    // let's use a unified format here that support multiple messages, though currently we only have one user prompt.
    var messages = [{"role": "user", "text": data.prompt}];
    var history_message_region = $("#history-message-region");
    history_message_region.empty();

    $.each(messages, function(i, message) {
        var icon = message.role == "user" ? "🧑" : "🤖";

        var $message_element = $("<div></div>").addClass("row").html(`
            <div class="col icon-col">
                <button class="role-icon" disabled>${icon}</button>
            </div>
            <div class="col message-col history-message-col">
                <xmp class="message-text">${message.text}</xmp>
            </div>
        `);

        history_message_region.append($message_element);
    });

    // now render the completions
    completion_a = data.completions[0];
    completion_b = data.completions[1];
    
    $("#completion-A-col").html(`
        <xmp class="message-text" id="${completion_a.model}-completion">${completion_a.completion}</xmp>
    `);
    $("#completion-B-col").html(`
        <xmp class="message-text" id="${completion_b.model}-completion">${completion_b.completion}</xmp>
    `);

    // Change the URL path with the current index
    window.history.pushState(null, '', `/instances/${index}`);
}


// clear everything
function clear_all() {
    $('#history-message-region').html(`
        <div class="row">
            <div class="col icon-col">
                <button class="role-icon" disabled>🧑</button>
            </div>
            <div class="col message-col history-message-col">
                <xmp class="message-text"></xmp>
            </div>
        </div>
    `);
    $('.completion-col').empty(); 
    $('input[type="checkbox"], input[type="radio"]').prop('checked', false);
    $('textarea').val('');
}


function show_alert(message, type, insert_after_selector, timeout=5000) {
    const alert_container = $(`<div class="alert alert-${type} mx-auto mt-2" style="max-width:500px" role="alert">${message}</div>`)[0];
    $(insert_after_selector)[0].insertAdjacentElement("afterend", alert_container);
    setTimeout(() => {
        alert_container.remove();
    }, timeout);
}

async function submit_evaluation() {
    try {
        // get the model name by trimming out the last `-completion` part
        const model_a = $("#completion-A-col").find("xmp").attr("id").slice(0, -11);
        const model_b = $("#completion-B-col").find("xmp").attr("id").slice(0, -11);
        const completion_a_is_acceptable = $("input[name='a-is-acceptable']:checked").val();
        const completion_b_is_acceptable = $("input[name='b-is-acceptable']:checked").val();
        const preference = $("input[name='preference-selection']:checked").val();
        
        // get the prompt and completions
        const prompt = $("#history-message-region").find("xmp").text();
        const completion_a = $("#completion-A-col").find("xmp").text();
        const completion_b = $("#completion-B-col").find("xmp").text();

        // make sure all the required fields are filled
        if (completion_a_is_acceptable == undefined || completion_b_is_acceptable == undefined || preference == undefined) {
            show_alert("Please fill in all the questions.", "danger", insert_after_selector="#evaluation-submit", timeout=5000);
            return;
        }
        const response = await fetch("/api/submit-evaluation", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                index: current_instance_index,
                model_a,
                model_b,
                prompt,
                completion_a,
                completion_b,
                completion_a_is_acceptable,
                completion_b_is_acceptable,
                preference,
                evaluator: username 
            }),
        });
        
        // if the response is 200, show the success message
        if (response.status == 200) {
            show_alert("Evaluation data is submitted successfully.", "success", insert_after_selector="#evaluation-submit", timeoutput=5000);
            console.log("Evaluation data is submitted successfully.");
            updateProgressBar();
            // Only move to next instance after submit
            setTimeout(() => {
                current_index++;
                rendere_instance(current_index);
                updateProgressBarAsync();
            }, 500);
        }
        else if (response.status == 409) {
            show_alert("You already submitted feedback for this instance. Moving to next...", "warning", insert_after_selector="#evaluation-submit", timeoutput=5000);
            setTimeout(() => {
                current_index++;
                rendere_instance(current_index);
            }, 1500);
        }
        else if (response.status == 401) {
            show_alert("You need to log in to submit evaluation data.", "danger", insert_after_selector="#evaluation-submit", timeoutput=5000);
        }
        else {
            console.log(response);
            show_alert("Error when submitting evaluation data. Please try again.", "danger", insert_after_selector="#evaluation-submit", timeoutput=5000);
            console.error("Error when submitting evaluation data:", response.status);
        }
    } catch (error) {
        show_alert("Error when submitting evaluation data. Please try again.", "danger", insert_after_selector="#evaluation-submit", timeoutput=5000);
        console.error("Error when submitting evaluation data:", error);
    }
}

$("#evaluation-submit").click(function () {
    // prevent default form submission
    event.preventDefault();
    submit_evaluation();
});



async function submit_feedback() {
    try {
        // get the model name by trimming out the last `-completion` part
        const model_a = $("#completion-A-col").find("xmp").attr("id").slice(0, -11);
        const model_b = $("#completion-B-col").find("xmp").attr("id").slice(0, -11);

        // get the prompt and completions
        const prompt = $("#history-message-region").find("xmp").text();
        const completion_a = $("#completion-A-col").find("xmp").text();
        const completion_b = $("#completion-B-col").find("xmp").text();

        // feedback
        const instance_quality = $("input[name='instance-quality']:checked").val();
        const comment = $("textarea[name='comment']").val();

        console.log("instance_quality:", instance_quality);
        console.log("comment:", comment);

        // make sure some fields are filled
        if (instance_quality == undefined && comment == "") {
            show_alert("No feedback is provided.", "danger", insert_after_selector="#feedback-submit", timeout=5000);
            return;
        }
        const response = await fetch("/api/submit-feedback", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                index: current_instance_index,
                model_a,
                model_b,
                prompt,
                completion_a,
                completion_b,
                instance_quality,
                comment,
                evaluator: username 
            }),
        });
        
        // if the response is 200, show the success message
        if (response.status == 200) {
            show_alert("Feedback is submitted successfully.", "success", insert_after_selector="#feedback-submit", timeoutput=5000);
            console.log("Feedback is submitted successfully.");
        }
        else if (response.status == 401) {
            show_alert("You need to log in to submit feedback.", "danger", insert_after_selector="#feedback-submit", timeoutput=5000);
        }
        else {
            console.log(response);
            show_alert("Error when submitting feedback data. Please try again.", "danger", insert_after_selector="#feedback-submit", timeoutput=5000);
            console.error("Error when submitting feedback data:", response.status);
        }
    } catch (error) {
        show_alert("Error when submitting feedback data. Please try again.", "danger", insert_after_selector="#feedback-submit", timeoutput=5000);
        console.error("Error when submitting evaluation data:", error);
    }
}

$("#feedback-submit").click(function () {
    // prevent default form submission
    event.preventDefault();
    submit_feedback();
});

// Navigation is now forward-only - prev button is disabled in template
// Users can only move forward through instances via Submit button

// Function to update the progress bar
async function updateProgressBar() {
    try {
        console.log("Fetching user progress...");
        const response = await fetch('/api/user-progress');
        console.log("Response status:", response.status);
        const data = await response.json();
        console.log("Progress data:", data);
        
        if (response.status === 200) {
            const percentage = data.percentage;
            const completed = data.completed;
            const total = data.total;
            
            console.log("Updating progress bar to", percentage, "%");
            
            // Update progress bar
            $('#progress-bar')
                .css('width', percentage + '%')
                .attr('aria-valuenow', percentage);
            
            // Update progress text
            $('#progress-text').text(`Completed evaluations: ${completed} / ${total}`);
            console.log("Progress text updated");
            
            // Update progress bar background color based on completion
            if (percentage === 100) {
                $('#progress-bar').addClass('bg-success').removeClass('bg-primary');
            }
        }
    } catch (error) {
        console.error("Error fetching progress:", error);
    }
}

// Update progress bar after instance is loaded (non-blocking)
function updateProgressBarAsync() {
    console.log("updateProgressBarAsync called");
    updateProgressBar().catch(err => console.log("Progress bar update failed, but that's OK"));
}

// Update progress bar when page loads (non-blocking)
$(document).ready(function() {
    console.log("Document ready - scheduling progress bar update");
    // Initialize with loading state
    $('#progress-text').text('Loading...');
    setTimeout(updateProgressBarAsync, 500); // Small delay to ensure instance is loaded
});